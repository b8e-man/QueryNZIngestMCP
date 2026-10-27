#!/usr/bin/env python3
"""Ingest libgen_compact.sql (MySQL dump) into SQLite.

Streams the 2GB dump, parses INSERT tuples with a quote-aware state
machine (handles \' escapes, NULLs, commas/parens inside strings),
and bulk-inserts into libgen.db. Raw values, no transformation.
"""
import sqlite3
import sys
import time

SQL_PATH = "/opt/data/annas-map-mcp/dumps/libgen_compact.sql"
DB_PATH = "/opt/data/annas-map-mcp/dumps/libgen.db"

COLUMNS = [
    "ID", "Title", "VolumeInfo", "Series", "Periodical", "Author", "Year",
    "Edition", "Publisher", "City", "Pages", "PagesInFile", "Language",
    "Topic", "Library", "Issue", "Identifier", "ISSN", "ASIN", "UDC", "LBC",
    "DDC", "LCC", "Doi", "Googlebookid", "OpenLibraryID", "Commentary",
    "DPI", "Color", "Cleaned", "Orientation", "Paginated", "Scanned",
    "Bookmarked", "Searchable", "Filesize", "Extension", "MD", "Generic",
    "Visible", "Locator", "Local", "TimeAdded", "TimeLastModified",
    "Coverurl", "Tags", "IdentifierWODash",
]
NCOL = len(COLUMNS)


def parse_values(chunk: str):
    """Parse the VALUES body of one INSERT statement. Yields tuples.

    Stops at a ';' outside strings — the dump packs multiple INSERT
    statements onto one line; without this, the NEXT statement's
    parenthesized column list gets parsed as a bogus row.
    """
    i, n = 0, len(chunk)
    while i < n:
        # find start of a tuple; ';' outside strings ends the statement
        while i < n and chunk[i] not in "(;":
            i += 1
        if i >= n or chunk[i] == ";":
            return
        i += 1  # skip '('
        row = []
        while i < n:
            c = chunk[i]
            if c == "'":
                # quoted string
                i += 1
                buf = []
                while i < n:
                    ch = chunk[i]
                    if ch == "\\":
                        nxt = chunk[i + 1] if i + 1 < n else ""
                        buf.append(
                            {"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(nxt, nxt)
                        )
                        i += 2
                    elif ch == "'":
                        i += 1
                        break
                    else:
                        buf.append(ch)
                        i += 1
                row.append("".join(buf))
            elif chunk.startswith("NULL", i):
                row.append(None)
                i += 4
            else:
                # bare token: number or keyword, up to ',' or ')'
                j = i
                while j < n and chunk[j] not in ",)":
                    j += 1
                tok = chunk[i:j].strip()
                row.append(tok if tok else None)
                i = j
            # after a value: ',' continues tuple, ')' ends it
            if i < n and chunk[i] == ",":
                i += 1
                continue
            if i < n and chunk[i] == ")":
                i += 1
                break
        yield tuple(row)


def main():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("DROP TABLE IF EXISTS books")
    conn.execute(
        "CREATE TABLE books ("
        + ", ".join(
            ('"%s" INTEGER' % c) if c == "ID" else ('"%s" TEXT' % c)
            for c in COLUMNS)
        + ")"
    )
    placeholders = ",".join("?" * NCOL)
    ins = "INSERT INTO books VALUES (" + placeholders + ")"

    batch = []
    total = 0
    bad = 0
    stmt = []
    in_stmt = False
    with open(SQL_PATH, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not in_stmt:
                if line.startswith("INSERT INTO `updated`"):
                    in_stmt = True
                    stmt = [line]
                continue
            stmt.append(line)
            if line.rstrip().endswith(";"):
                in_stmt = False
                text = "".join(stmt)
                stmt = []
                marker = "VALUES"
                pos = text.find(marker)
                if pos < 0:
                    continue
                body = text[pos + len(marker):]
                for row in parse_values(body):
                    if len(row) == NCOL:
                        batch.append(row)
                    else:
                        bad += 1
                    if len(batch) >= 20000:
                        conn.executemany(ins, batch)
                        total += len(batch)
                        batch.clear()
                        if total % 200000 == 0:
                            conn.commit()
                            print(f"{total} rows {time.time()-t0:.0f}s", flush=True)
    if batch:
        conn.executemany(ins, batch)
        total += len(batch)
    conn.commit()
    conn.execute("CREATE INDEX idx_id ON books(ID)")
    conn.commit()
    conn.close()
    print(f"DONE rows={total} bad={bad} secs={time.time()-t0:.0f}")


if __name__ == "__main__":
    main()
