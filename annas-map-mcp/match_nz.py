#!/usr/bin/env python3
"""NZ filter over libgen.db — builds nz_map table with recorded signals.

Design: score-based matcher. Every match stores WHY it matched (signals),
so nothing is a silent decision. Two passes:
  pass 1: strong signals (NZ publishers, 'New Zealand'/'Aotearoa' in
          title/series, te reo markers, distinctive NZ cities)
  pass 2: author census — authors with >=2 strong matches seed the
          extended author list, widening recall with recorded provenance.

Raw fields copied verbatim. No transformation of source data.
"""
import json
import re
import sqlite3
import time

DB_PATH = "/opt/data/annas-map-mcp/dumps/libgen.db"

# --- signal dictionaries ---------------------------------------------------

# Distinctive NZ publishers (match against Publisher field, case-insensitive)
NZ_PUBLISHERS = [
    "auckland university press", "victoria university press",
    "bridget williams", "whitcoulls", "reed publishing", "reed nz",
    "heinemann nz", "heinemann (nz", "penguin books new zealand",
    "penguin new zealand", "penguin nz", "random house new zealand",
    "harpercollins new zealand", "harpercollins nz", "hazard press",
    "dunmore press", "david ling", "hodder moa", "moa beckett",
    "bateman", "exisle", "oratia", "libro international",
    "cape catley", "four winds press", "government printer",
    "gp publications", "learning media", "nz institute",
    "new zealand institute", "sweet & maxwell nz", "sweet and maxwell nz",
    "craig potton", "potton & burton", "potton and burton",
    "white cloud", "upstart press", "massey university press",
    "otago university press", "canterbury university press",
    "waikato university", "wilson & horton", "wilson and horton",
    "ah reed", "a h reed", "paul's book arcade", "blackwood & janet paul",
    "collins (nz", "collins auckland", "methuen nz", "macmillan nz",
    "caxton press", "piwakawaka", "steele roberts", "seraphine press",
    "one tree house", "scholastic new zealand", "new zealand council",
    "nz government", "new zealand government", "department of internal affairs",
    "royal society of new zealand", "tourism holdings",
]

# Distinctive NZ cities/towns (rare elsewhere -> strong signal).
# Deliberately EXCLUDED from strong (foreign place names, false-positive
# sources): nelson, hamilton, canterbury, thames, stratford, shannon,
# greytown, huntly, raglan, marton, woodville, westport, taipa, russell,
# marlborough, northland, eltham, cambridge, richmond, hastings (UK town —
# Agrippa's "Hastings, UK" caught in QA).
NZ_CITIES_STRONG = [
    "new zealand", "wellington", "christchurch", "dunedin", "palmerston north",
    "invercargill", "tauranga", "whangarei", "napier",
    "queenstown", "rotorua", "new plymouth", "whanganui", "wanganui",
    "lower hutt", "porirua", "timaru", "blenheim", "gisborne",
    "taupo", "oamaru", "masterton", "feilding", "te awamutu", "tokoroa",
    "ashburton", "greymouth", "hokitika", "kaikohe", "levin",
    "waikato", "manawatu", "otago", "hawke's bay", "hawkes bay",
    "taranaki", "rangiora", "kaiapoi", "wairoa",
    "paeroa", "matamata", "taumarunui", "hawera", "waitara",
    "pahiatua", "dannevirke", "waipukurau", "waipawa", "martinborough",
    "carterton", "opunake",
    "mount maunganui", "whakatane", "opotiki", "kawerau",
    "kerikeri", "paihia", "kaitaia", "dargaville",
    "pukekohe", "waiuku", "tuakau", "ngaruawahia", "morrinsville",
    "te kuiti", "otorohanga", "putaruru", "turangi",
]

# Ambiguous names shared with UK/US/etc -> weak signal on its own
NZ_CITIES_WEAK = [
    "auckland", "nelson", "richmond", "cambridge", "hamilton",
    "canterbury", "thames", "stratford", "shannon", "greytown",
    "huntly", "raglan", "marton", "woodville", "westport", "taipa",
    "russell", "marlborough", "northland", "eltham", "hastings",
]

# Te reo / NZ subject markers in title/series/author
TE_REO = [
    "māori", "maori", "aotearoa", "pākehā", "pakeha", "treaty of waitangi",
    "waitangi", "iwi", "hapū", "hapu", "whānau", "whanau", "kapa haka",
    "te reo", "hongi", "marae", "tangata whenua", "kiwi",
]

# Word-bounded: bare substrings match inside foreign words ('Profiwissen',
# 'Erziehungswissenschaft' contain 'iwi'). First-match order preserved.
TEREO_RE = re.compile(r"\b(" + "|".join(map(re.escape, TE_REO)) + r")\b")

# Explicit NZ context inside a City string disambiguates foreign names:
# 'Nelson, New Zealand', 'Auckland N.Z.', 'Hamilton NZ'.
NZ_CONTEXT_RE = re.compile(r"new zealand|n\.?\s?z\.?\b", re.I)


def build():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS nz_map")
    conn.execute(
        """CREATE TABLE nz_map (
        ID INTEGER PRIMARY KEY,
        Title TEXT, Author TEXT, Year TEXT, Publisher TEXT, City TEXT,
        Language TEXT, Topic TEXT, Series TEXT, Extension TEXT,
        Identifier TEXT, OpenLibraryID TEXT, Googlebookid TEXT,
        MD5 TEXT, Signals TEXT, Score INTEGER, Pass TEXT)"""
    )

    def scan(where_extra, pass_name, author_set=None):
        cur = conn.execute(
            "SELECT ID, Title, Author, Year, Publisher, City, Language, Topic,"
            " Series, Extension, Identifier, OpenLibraryID, Googlebookid, MD"
            " FROM books"
        )
        n = 0
        for (bid, title, author, year, pub, city, lang, topic, series,
             ext, ident, olid, gbid, md5) in cur:
            signals = []
            score = 0
            tl = (title or "").lower()
            al = (author or "").lower()
            pl = (pub or "").lower()
            cl = (city or "").lower()
            sl = (series or "").lower()

            for p in NZ_PUBLISHERS:
                if p in pl:
                    signals.append("publisher:" + p)
                    score += 3
                    break
            for m in ("new zealand", "aotearoa"):
                if m in tl or m in sl:
                    signals.append("title:" + m)
                    score += 3
                    break
            tereo_m = TEREO_RE.search(tl)
            if tereo_m:
                signals.append("tereo:" + tereo_m.group(1))
                score += 2
            strong_city = False
            for c in NZ_CITIES_STRONG:
                if c in cl:
                    signals.append("city:" + c)
                    score += 2
                    strong_city = True
                    break
            if not strong_city:  # never double-count one place name
                for c in NZ_CITIES_WEAK:
                    if c in cl:
                        if NZ_CONTEXT_RE.search(cl):
                            # 'Nelson, New Zealand' / 'Auckland N.Z.' — the
                            # ambiguity is resolved by the string itself
                            signals.append("city:" + c + "_nz")
                            score += 2
                            strong_city = True
                        else:
                            signals.append("city_weak:" + c)
                            score += 1
                        break
            if author_set:
                # EXACT normalized author match only — substring matching on
                # name fragments floods the map with non-NZ namesakes.
                na = re.sub(r"\s+", " ", al).strip().rstrip(".")
                if na and na in author_set:
                    signals.append("author_exact:" + na)
                    score += 3

            if score >= where_extra and (pass_name == "1" or signals):
                if pass_name == "1":
                    cur2 = conn.execute(
                        "INSERT OR REPLACE INTO nz_map VALUES (?,?,?,?,?,?,?,?,?,?"
                        ",?,?,?,?,?,?,?)",
                        (bid, title, author, year, pub, city, lang, topic, series,
                         ext, ident, olid, gbid, md5,
                         json.dumps(signals, ensure_ascii=False), score, pass_name),
                    )
                else:
                    cur2 = conn.execute(
                        "INSERT OR IGNORE INTO nz_map VALUES (?,?,?,?,?,?,?,?,?,?"
                        ",?,?,?,?,?,?,?)",
                        (bid, title, author, year, pub, city, lang, topic, series,
                         ext, ident, olid, gbid, md5,
                         json.dumps(signals, ensure_ascii=False), score, pass_name),
                    )
                n += cur2.rowcount if cur2.rowcount > 0 else 0
        return n

    n1 = scan(3, "1")  # strong matches only
    conn.commit()
    print(f"pass1 strong: {n1} rows {time.time()-t0:.0f}s", flush=True)

    # Author pass-2 seeds: authors with a REPEATED NZ publication footprint —
    # >=2 strong rows carrying a publisher/city signal (NZ-published), not
    # merely NZ-titled. Otherwise guidebook brands ('lonely planet' via
    # 'Lonely Planet New Zealand'), orgs ('oecd'), placeholders ('coll.')
    # and foreign authors of NZ books ('david hackett fischer') flood the
    # map with non-NZ works. Person-like authors only (2+ tokens).
    PLACEHOLDERS = {"coll.", "coll", "anon", "anon.", "anonymous", "unknown",
                    "various", "n/a", "ed.", "eds.", "editor", "author"}
    authors = {}
    for sigs, a in conn.execute(
            "SELECT Signals, Author FROM nz_map WHERE Pass='1'"):
        if not a:
            continue
        try:
            sigl = json.loads(sigs or "[]")
        except (TypeError, ValueError):
            continue
        if not any(s.startswith("publisher:") or s.startswith("city:")
                   for s in sigl):
            continue
        na = re.sub(r"\s+", " ", a.lower()).strip().rstrip(".")
        if len(na) < 4 or na in PLACEHOLDERS:
            continue
        if " " not in na and "," not in na:
            continue  # single token = brand/org/placeholder, not a person
        authors[na] = authors.get(na, 0) + 1
    seed = {a for a, c in authors.items() if c >= 2}
    print(f"pass2 author seeds: {len(seed)}", flush=True)

    n2 = scan(3, "2", author_set=seed)  # author-exact rows + score>=3 rows
    conn.commit()

    # Tier 3: single-signal evidence (strong city alone or te reo marker
    # alone, score 2). Below the pass-1 floor but real evidence — recorded
    # as its own tier so it is inspectable, not invisible.
    n3 = scan(2, "3")
    conn.commit()
    conn.execute("CREATE INDEX idx_score ON nz_map(Score DESC)")
    conn.commit()
    total_map = conn.execute("SELECT COUNT(*) FROM nz_map").fetchone()[0]
    conn.close()
    print(f"pass2 added: {n2} pass3 added: {n3} map total: {total_map}"
          f" overall {time.time()-t0:.0f}s")


if __name__ == "__main__":
    build()
