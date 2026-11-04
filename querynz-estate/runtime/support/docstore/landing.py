"""The one landing wrapper (the estate's plan 1.10), adapted to this box.

Unchanged from the estate's: bytes to `<root>/<aa>/<sha256>` atomically; the
`docs.documents` / `docs.names` / `docs.landings` rows through the caller's
conn (the shim's SQLite); a second landing of the same bytes adds a name and
nothing more (`new` is False); a failed landing leaves a `docs.landings` line
and raises.

Added here: when bytes land for the first time, a manifest row is appended to
`/opt/data/querynz-estate/sources/<source>/manifest.jsonl` — the handover's
per-source manifest format — so the estate-* corpora pick the document up
through their incremental tailer. The row's `file` is the absolute store path
(the handover's rows carry `<sha>.<ext>` names inside their source folder; both
resolve). A later landing of the same bytes under a new name is recorded in
the store's tables and the run record, not rewritten into the manifest: the
manifest stays append-only, one row per document.

    from support.docstore.landing import land, copy_from_old
    ref, new = land(data, name="x.pdf", source="charities", conn=conn)
"""
import datetime as dt
import json
import os

from support.docstore import DocumentRef, describe

ROOT = os.environ.get("QV4_DOCS") or "/opt/data/querynz-estate/store"
HERE = os.path.dirname(os.path.abspath(__file__))
TABLES_SQL = os.path.join(HERE, "tables.sql")
SOURCES_ROOT = os.environ.get("QV4_SOURCES") or "/opt/data/querynz-estate/sources"


def tables_sql() -> str:
    with open(TABLES_SQL, encoding="utf-8") as f:
        return f.read()


def path_for(sha256: str, root: str = None) -> str:
    return os.path.join(root or ROOT, sha256[:2], sha256)


def write_bytes(data: bytes, sha256: str, root: str = None) -> str:
    """The bytes on disk, atomically; a file already there is left alone
    (it is the same bytes by construction)."""
    p = path_for(sha256, root)
    if os.path.exists(p):
        return p
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + f".tmp{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, p)
    return p


def _now_spaced() -> str:
    return dt.datetime.now().astimezone().isoformat().replace("T", " ", 1)


def _sniff_mime(data: bytes, name: str, content_type: str) -> str:
    """The MIME type from the bytes' leading bytes (the handover's rule);
    the response's own type is the fallback."""
    head = data[:512].lstrip()
    low = (name or "").lower()
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head[:1] == b"<":
        return "text/html"
    if head[:1] in (b"{", b"["):
        return "application/json"
    if head.startswith(b"<?xml"):
        return "text/xml"
    if head.startswith(b"PK"):
        if low.endswith(".xlsx"):
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if low.endswith(".docx"):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return "application/zip"
    if head.startswith((b"\"\"", b"-")) or (low.endswith(".csv") and b"," in head):
        return "text/csv"
    return content_type or "application/octet-stream"


def _manifest_row(ref: DocumentRef, path: str, name: str, name_kind: str,
                  content_type: str, source: str):
    d = os.path.join(SOURCES_ROOT, source)
    os.makedirs(d, exist_ok=True)
    row = {
        "sha256": ref.sha256,
        "size": ref.size,
        "kind": ref.kind,
        "content_type": _sniff_mime(open(path, "rb").read(512), name, content_type),
        "file": path,
        "urls": ([{"url": name, "via": [f"{source}.capture"]}]
                 if name_kind == "url" and name else []),
        "archive_replay_urls": [],
        "names": [name] if name else [],
        "landings": 1,
        "first_landed": _now_spaced(),
        "last_landed": _now_spaced(),
        "fetched_at": (ref.fetched_at or "").replace("T", " ", 1),
        "landed_at": _now_spaced(),
        "withdrawn": False,
        "withdrawn_reason": None,
        "problem": None,
    }
    if ref.content_sha256:
        row["content_sha256"] = ref.content_sha256
    with open(os.path.join(d, "manifest.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def land(data: bytes, *, name: str, source: str, conn, kind_hint: str = "", name_kind: str = "file",
         fetched_at: str = None, root: str = None, content_type: str = ""):
    """Land bytes: (DocumentRef, new). Raises on a failure after writing
    the landing line; the caller's transaction is committed on success."""
    ref = describe(data, name, content_type, source, fetched_at)
    try:
        path = write_bytes(data, ref.sha256, root)
        with conn.transaction():
            row = conn.execute("SELECT 1 FROM docs.documents WHERE sha256 = %s", (ref.sha256,)).fetchone()
            new = row is None
            if new:
                conn.execute(
                    "INSERT INTO docs.documents (sha256, size, kind, source, content_sha256, fetched_at, path) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (ref.sha256, ref.size, ref.kind, source, ref.content_sha256 or None, ref.fetched_at, path))
            conn.execute(
                "INSERT INTO docs.names (sha256, name, kind) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (ref.sha256, name, name_kind))
            conn.execute("INSERT INTO docs.landings (sha256, source, name, ok, new) VALUES (%s, %s, %s, true, %s)",
                         (ref.sha256, source, name, new))
        if new:
            _manifest_row(ref, path, name, name_kind, content_type, source)
    except Exception as exc:  # noqa: BLE001 — the landing line is the record of the failure
        try:
            with conn.transaction():
                conn.execute("INSERT INTO docs.landings (sha256, source, name, ok, why) VALUES (%s, %s, %s, false, %s)",
                             (ref.sha256, source, name, f"{type(exc).__name__}: {str(exc)[:300]}"))
        except Exception:  # noqa: BLE001
            pass
        raise
    return ref, new


def copy_from_old(old_path: str, source: str, conn, root: str = None):
    """Case 1 of plan 1.10: a file the old estate holds, copied by hash,
    read-only, into the store; its old path is one of its names."""
    with open(old_path, "rb") as f:
        data = f.read()
    st = os.stat(old_path)
    fetched = dt.datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds")
    ref, new = land(data, name=os.path.basename(old_path), source=source, conn=conn, fetched_at=fetched, root=root)
    with conn.transaction():
        conn.execute("INSERT INTO docs.names (sha256, name, kind) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                     (ref.sha256, old_path, "old-path"))
    return ref, new


def names_of(sha256: str, conn) -> list:
    return [r[0] for r in conn.execute("SELECT name FROM docs.names WHERE sha256 = %s ORDER BY seen_at, name", (sha256,))]


def read_bytes(ref_or_sha, root: str = None) -> bytes:
    sha = ref_or_sha.sha256 if isinstance(ref_or_sha, DocumentRef) else ref_or_sha
    with open(path_for(sha, root), "rb") as f:
        return f.read()
