"""The database shim for the estate's capture code on this box.

The estate's `support.db` opened Postgres; this opens SQLite and presents the
same surface so the lanes' capture code runs unmodified:

    from support import db
    with db.connect(db.OWNER_KEY, "querynz_v4", autocommit=True) as conn:
        conn.execute("SET statement_timeout = '60s'")     # no-op
        conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (job,))  # 1
        with conn.transaction():
            conn.execute("INSERT INTO charities.capture_passes (...) "
                         "VALUES (%s, %s, %s) RETURNING pass_id", (...))

What the shim does per call: sqlglot transpiles postgres -> sqlite (now(),
~, casts, %s -> ?), multi-statement strings are split, SET/CREATE SCHEMA are
no-ops, `= ANY(?)` becomes a json_each membership test, list parameters are
json-encoded to match, BIGSERIAL PRIMARY KEY becomes INTEGER PRIMARY KEY
(rowid alias: the insert assigns). Qualified names keep their schema: each
lane schema and `docs` is an ATTACHed database file under runtime/db/,
created on first touch. Advisory locks always grant (the cron wrapper holds
the real lock, one run per lane). Timestamps read back as aware datetimes
(naive values are UTC), so they compare with the clock's aware datetimes.
"""
import datetime as dt
import json
import os
import re
import sqlite3

import sqlglot

OWNER_KEY = "shim"
HERE = os.path.dirname(os.path.abspath(__file__))
DBDIR = os.environ.get("QV4_DB") or os.path.join(os.path.dirname(HERE), "db")

_MULTI = re.compile(r";")
_ANY = re.compile(r"=\s*ANY\s*\(\s*\?\s*\)")
_SERIAL_PK = re.compile(
    r"\b(\w+)\s+(?:BIGSERIAL|SERIAL8|SERIAL4|SERIAL)\s+PRIMARY\s+KEY\b",
    re.I)
_IDX_ON = re.compile(
    r"CREATE (UNIQUE )?INDEX (IF NOT EXISTS )?([A-Za-z_]\w*) ON ([A-Za-z_]\w*)\.")
_FK_QUAL = re.compile(r"REFERENCES [A-Za-z_]\w*\.")
_ADDCOL = re.compile(r"ADD COLUMN IF NOT EXISTS", re.I)
_ARRAYT = re.compile(r"\bARRAY\s*<[^>]*>", re.I)
_NAMEPAT = re.compile(r"%\((\w+)\)s")


def _fix_conflict(t: str) -> str:
    """Strip sqlglot's NULLS LAST/FIRST out of ON CONFLICT target lists."""
    return re.sub(
        r"ON CONFLICT\s*\(([^)]*)\)",
        lambda m: "ON CONFLICT ("
        + re.sub(r"\s+NULLS (?:LAST|FIRST)", "", m.group(1), flags=re.I) + ")",
        t, flags=re.I)


def _sql_literal(v) -> str:
    """A psycopg2-style client-side literal for %(name)s interpolation."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple, set)):
        return "(" + ",".join(_sql_literal(x) for x in v) + ")"
    if isinstance(v, (dt.datetime, dt.date)):
        v = v.isoformat()
    return "'" + str(v).replace("'", "''") + "'"


def _adapt_datetime(v):
    return v.isoformat()


sqlite3.register_adapter(dt.datetime, _adapt_datetime)
sqlite3.register_adapter(dt.date, lambda v: v.isoformat())


def _conv_ts(b):
    s = b.decode("utf-8", "replace") if isinstance(b, bytes) else str(b)
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return s
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def _conv_date(b):
    s = b.decode("utf-8", "replace") if isinstance(b, bytes) else str(b)
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return s


def _conv_bool(b):
    if isinstance(b, bytes):
        return b not in (b"\x00", b"f", b"false", b"0", b"")
    return bool(b)


for _t in ("timestamptz", "timestamp", "datetime", "TIMESTAMPTZ", "TIMESTAMP"):
    sqlite3.register_converter(_t, _conv_ts)
for _t in ("date", "DATE"):
    sqlite3.register_converter(_t, _conv_date)
for _t in ("boolean", "bool", "BOOLEAN", "BOOL"):
    sqlite3.register_converter(_t, _conv_bool)


def _regexp(pattern, value):
    if value is None:
        return None        # NULL REGEXP ... is NULL: CHECK passes, as in PG
    try:
        return 1 if re.search(pattern, str(value)) else 0
    except re.error:
        return 0


class _BoolOr:
    def __init__(self):
        self.v = 0

    def step(self, x):
        self.v = self.v or (1 if x else 0)

    def finalize(self):
        return self.v


class _BoolAnd:
    def __init__(self):
        self.v = 1

    def step(self, x):
        self.v = self.v and (1 if x else 0)

    def finalize(self):
        return self.v


class _Cursor:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, n=None):
        return self._cur.fetchmany(n) if n else self._cur.fetchmany()

    def __iter__(self):
        return iter(self._cur)

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    def close(self):
        self._cur.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._cur.close()


class _Transaction:
    def __init__(self, conn):
        self._c = conn

    def __enter__(self):
        if self._c._depth == 0:
            self._c._raw.execute("BEGIN IMMEDIATE")
        self._c._depth += 1
        return self

    def __exit__(self, et, ev, tb):
        self._c._depth -= 1
        if self._c._depth == 0:
            if et is None:
                self._c._raw.execute("COMMIT")
            else:
                self._c._raw.execute("ROLLBACK")


class Conn:
    def __init__(self, database: str):
        os.makedirs(DBDIR, exist_ok=True)
        self._raw = sqlite3.connect(
            os.path.join(DBDIR, database + ".sqlite"),
            detect_types=sqlite3.PARSE_DECLTYPES, isolation_level=None)
        self._raw.row_factory = None
        self._depth = 0
        self._attached = set()
        for name, fn in (("regexp", _regexp),
                         ("pg_try_advisory_lock", lambda x: 1),
                         ("pg_advisory_unlock", lambda x: 1),
                         ("hashtext", lambda s: hash(str(s)) & 0x7FFFFFFF),
                         ("pg_get_serial_sequence", lambda a, b: "")):
            self._raw.create_function(name, -1, fn)
        self._raw.create_aggregate("bool_or", 1, _BoolOr)
        self._raw.create_aggregate("bool_and", 1, _BoolAnd)
        self._attach("information_schema")
        self._raw.execute(
            "CREATE TABLE IF NOT EXISTS information_schema.tables "
            "(table_schema TEXT, table_name TEXT)")
        self._raw.execute(
            "CREATE TABLE IF NOT EXISTS information_schema.columns "
            "(table_schema TEXT, table_name TEXT, column_name TEXT, data_type TEXT)")
        self._attach("docs")
        docs_ddl = os.path.join(HERE, "docstore", "tables.sql")
        if os.path.exists(docs_ddl):
            with open(docs_ddl, encoding="utf-8") as f:
                self.execute(f.read())
        self._sync_info_schema()

    # -- schemas -----------------------------------------------------------
    def _attach(self, schema: str):
        if schema in self._attached:
            return
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            return
        path = os.path.join(DBDIR, schema + ".sqlite")
        self._raw.execute("ATTACH DATABASE ? AS " + schema, (path,))
        self._attached.add(schema)

    def _sync_info_schema(self):
        """Rebuild information_schema.tables/.columns from every attached
        schema's sqlite_master, so the lanes' schema introspection queries
        run unmodified."""
        self._raw.execute("DELETE FROM information_schema.tables")
        self._raw.execute("DELETE FROM information_schema.columns")
        for s in sorted(self._attached):
            if s == "information_schema":
                continue
            self._raw.execute(
                f"INSERT INTO information_schema.tables "
                f"SELECT '{s}', name FROM {s}.sqlite_master "
                f"WHERE type IN ('table', 'view')")
            for (tname,) in self._raw.execute(
                    f"SELECT name FROM {s}.sqlite_master WHERE type = 'table'"):
                for row in self._raw.execute(f"PRAGMA {s}.table_info({tname})"):
                    self._raw.execute(
                        "INSERT INTO information_schema.columns VALUES (?,?,?,?)",
                        (s, tname, row[1], row[2]))

    def _autofix(self, sql: str):
        """Attach any qualified schema the statement names that is missing."""
        bare = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
        bare = re.sub(r"--[^\n]*", " ", bare)
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_]", bare):
            s = m.group(1)
            if s.lower() not in ("sqlite_master", "sqlite_temp") \
                    and s not in self._attached:
                self._attach(s)

    # -- statements --------------------------------------------------------
    def _transpile(self, sql: str, params):
        sql = sql.strip()
        if not sql:
            return []
        if isinstance(params, dict):
            # psycopg2 dict style: the driver interpolates client-side
            sql = _NAMEPAT.sub(lambda m: _sql_literal(params.get(m.group(1))), sql)
            sql = sql.replace("%%", "%")
            params = None
        params = list(params) if params is not None else None
        if params:
            params = [json.dumps(p) if isinstance(p, (list, tuple, set)) else p
                      for p in params]
        out = []
        for stmt in sqlglot.parse(sql, read="postgres"):
            t = stmt.sql(dialect="sqlite")
            up = re.sub(r"/\*.*?\*/", " ", t, count=8, flags=re.S)
            up = re.sub(r"^\s*(--[^\n]*\n\s*)*", "", up).lstrip().upper()
            if up.startswith(("CREATE SCHEMA", "DROP SCHEMA", "ALTER SCHEMA",
                              "SET ", "SHOW ", "RESET ", "DISCARD ")):
                continue
            if re.match(r"ALTER TABLE .*\b(ADD|DROP) CONSTRAINT\b", up):
                continue        # sqlite has no table constraints after create
            # sqlite grammar fixes (schema kept on the index name; FKs are
            # parse-only since PRAGMA foreign_keys stays off):
            if _IDX_ON.search(t):
                t = re.sub(r"\s+NULLS (LAST|FIRST)", "", t, flags=re.I)
            t = _IDX_ON.sub(
                lambda m: f"CREATE {m.group(1) or ''}INDEX {m.group(2) or ''}"
                          f"{m.group(4)}.{m.group(3)} ON ", t)
            t = _FK_QUAL.sub("REFERENCES ", t)
            t = _ADDCOL.sub("ADD COLUMN", t)
            t = _ARRAYT.sub("TEXT", t)
            t = _fix_conflict(t)
            t = _ANY.sub("IN (SELECT value FROM json_each(?))", t)
            t = _SERIAL_PK.sub(r"\1 INTEGER PRIMARY KEY", t)
            out.append(t)
        return [(t, params) for t in out]

    def execute(self, sql: str, params=None):
        if "information_schema" in sql:
            self._sync_info_schema()
        jobs = self._transpile(sql, params)
        if not jobs:
            return _Cursor(self._raw.execute("SELECT 1 WHERE 0"))
        self._autofix(sql)
        cur = None
        for t, p in jobs:
            try:
                cur = self._raw.execute(t, p or [])
            except sqlite3.OperationalError as e:
                m = re.search(r"no such database: (\w+)", str(e))
                if m:
                    self._attach(m.group(1))
                    cur = self._raw.execute(t, p or [])
                elif "duplicate column name" in str(e):
                    pass        # ADD COLUMN IF NOT EXISTS, honoured
                else:
                    raise
        return _Cursor(cur)

    # -- psycopg surface ---------------------------------------------------
    def transaction(self):
        return _Transaction(self)

    def cursor(self):
        return _Cursor(self._raw.cursor())

    def commit(self):
        pass

    def close(self):
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def connect(owner_key=None, database: str = "querynz_v4", autocommit: bool = True):
    return Conn(database)
