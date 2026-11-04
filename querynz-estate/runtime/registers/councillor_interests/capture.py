"""How this lane's documents arrive: case 3 of plan 1.10, captured once,
politely, through the fetch gate and the landing wrapper only.

There is no collected file: every council keeps its own register of its
elected members' pecuniary interests and publishes a summary on its own
website (Local Government Act 2002, Part 4 subpart 3, in force 20 November
2022); no department gathers them (searched 22 October 2026). So the lane
asks each council's own pages. `REGISTERS` is the survey's list (22 October
2026): for each of the 78 councils (the Department of Internal Affairs'
council list, data.govt.nz `council-contact-details`, `b6a3c710…`) its
current host, the page that publishes or links its register, and a register
document's address where a search showed one. The addresses were found by
web search (names of councils only) and every page was read through the
gate.

A run, at most monthly per council (registers change each February and on
a member's change): ask the landing page; land it; take every link on it,
on the council's own host, that names pecuniary interests or an interests
register; ask each such document once (a PDF is landed and held, never
read: plan 6.3, ruling 79) and each such page once a month. A
register PDF address the survey found is asked once if no page links it.
Off-peak (22:00 to 06:00 NZ time) unless `--anytime`, one request at a time,
`FLOOR_S` apart, a budget per run. A 403, 429, 5xx, challenge page or gate
refusal holds that council's host (`capture_held_hosts`, hard limit 6): not
asked again until a session reads why; the run goes on to the next council.
A host the gate itself holds (ruling 141) is passed over with nothing
written, so a person's clearing of the gate is the one clearing it needs.
A redirect off the host is not followed. A council whose website terms bar
automated access (`TERMS_BAR`) is not asked. The position on file is
`position/councillors-registers-of-interests.md` (the integrator moves it).

    python -m registers.councillor_interests.capture [--anytime] [--budget-s N] [--only COUNCIL]
"""
import argparse
import datetime as dt
import html
import os
import re
import sys
import time
import urllib.parse
from zoneinfo import ZoneInfo

import support.fetchgate as fg

SOURCE = SCHEMA = "councillor_interests"
JOB = "qv4-councillor-interests-capture"
FLOOR_S = 5.0
OFF_PEAK = (22, 6)
EVERY_DAYS = 30
DEFAULT_BUDGET_S = 2 * 3600
NZ = ZoneInfo("Pacific/Auckland")
HERE = os.path.dirname(os.path.abspath(__file__))
READING = "-- ── the reading"
POSITIONS = os.environ.get("QV4_POSITIONS") or None
COUNCIL_LIST_SHA = "b6a3c7102ca288c97fe1bad88249587a4b0906b2a198eb9ce841c3c336be011c"
#: a link that names the register: in its address or its words
REGISTER_LINK = re.compile(r"pecuniar|pecuinar|register[-_ %20]*of[-_ %20]*(members[-_ %20’'s]*)?interest|interests?[-_ %20]*register"
                           r"|members[-_ %20’'s]*interests|declarations?[-_ %20]*of[-_ %20]*interest|registered[-_ %20]*interests",
                           re.I)
NOT_SENT = "not sent: "
SERVER_ERRORS = (500, 502, 503, 504)
DOC = re.compile(r"\.pdf($|\?)|/repository/libraries/|/__data/assets/pdf_file/|/document/serve|/filelink/|/media/[a-z0-9]{8}/", re.I)

#: councils whose website terms bar automated access, read through the gate on 22 October 2026 (sha256 of the terms
#: page): not captured beyond the survey until Arthur rules (queue: whether-to-capture-councils-whose-terms-bar-
#: automated-access, no default)
TERMS_BAR = {
    "Auckland Council": "terms e58a2ac9…: 'You must not use automated tools, such as bots or web scrapers, to access our website' unless a public search engine",
    "South Waikato District Council": "terms ae3f55ce…: not to use the website 'to spam, phish, pharm, pretext, spider, crawl, or scrape'",
    "Waimakariri District Council": "terms b3ed5bac…: not to 'use a harvesting bot, robot, spider, scraper, or other unauthorised automated means to access the Websites'",
}

#: the document stores a council's own server redirects its register files to (measured 2 November 2026: the 302s of
#: 22 October): a redirect from the council's address to one of these is followed once, for that council only
DOC_HOSTS = {
    "Hutt City Council": ("hccpublicdocs.azurewebsites.net",),
    "Porirua City Council": ("storage.googleapis.com",),
    "Tasman District Council": ("tasmandc-publicdocs.azurewebsites.net",),
}

#: council → (host, the page that publishes or links the register, a register document's address); None where the
#: survey found none. From the survey of 22 October 2026 (web search for addresses; pages read through the gate).
REGISTERS = {
    "Ashburton District Council": ("www.ashburtondc.govt.nz", "https://www.ashburtondc.govt.nz/council/governance/elected-members/ashburton-district-council", None),
    "Auckland Council": ("www.aucklandcouncil.govt.nz", "https://www.aucklandcouncil.govt.nz/en/about-auckland-council/how-auckland-council-works/elected-members-remuneration-declarations-interest/elected-members-declarations-search.html", None),
    "Bay of Plenty Regional Council": ("www.boprc.govt.nz", "https://www.boprc.govt.nz/your-council/council-and-region/your-councillors/", None),
    "Buller District Council": ("bullerdc.govt.nz", None, "https://bullerdc.govt.nz/media/tanhlcqo/register-of-pecuniary-interests-to-16-february-2026.pdf"),
    "Canterbury Regional Council": ("www.ecan.govt.nz", "https://www.ecan.govt.nz/about/your-council/our-team/councillors", None),
    "Carterton District Council": ("cdc.govt.nz", "https://cdc.govt.nz/governance-documents/", "https://cdc.govt.nz/wp-content/uploads/2026/03/Summary-EM-Pecuniary-Interests-28-Jan-2026.pdf"),
    "Central Hawke's Bay District Council": ("www.chbdc.govt.nz", None, "https://www.chbdc.govt.nz/assets/Document-Library/Governance/2025-Summary-of-Pecuniary-and-other-specified-Interests-of-Elected-members-of-Central-Hawke.pdf"),
    "Central Otago District Council": ("www.codc.govt.nz", "https://www.codc.govt.nz/publications/policies", None),
    "Chatham Islands Council": ("www.cic.govt.nz", None, None),
    "Christchurch City Council": ("ccc.govt.nz", "https://ccc.govt.nz/the-council/how-the-council-works/organisation-structure/register-of-interests", None),
    "Clutha District Council": ("www.cluthadc.govt.nz", None, None),
    "Dunedin City Council": ("www.dunedin.govt.nz", "https://www.dunedin.govt.nz/council/local-governance-statement/register-of-members-pecuniary-interests", None),
    "Far North District Council": ("www.fndc.govt.nz", "https://www.fndc.govt.nz/Council/Governance", None),
    "Gisborne District Council": ("www.gdc.govt.nz", None, None),
    "Gore District Council": ("www.goredc.govt.nz", "https://www.goredc.govt.nz/council/elected-members", None),
    "Grey District Council": ("www.greydc.govt.nz", None, None),
    "Hamilton City Council": ("hamilton.govt.nz", "https://hamilton.govt.nz/your-council/about-council/mayor-and-councillors", "https://hamilton.govt.nz/assets/Uploads/Documents/Content-Documents/Your-Council/Summary-of-Pecuniary-Interests-2025-2028.pdf"),
    "Hastings District Council": ("www.hastingsdc.govt.nz", "https://www.hastingsdc.govt.nz/our-council/mayor-and-councillors/register-of-interests/", None),
    "Hauraki District Council": ("www.hauraki-dc.govt.nz", "https://www.hauraki-dc.govt.nz/council/mayor-councillors/pecuniary-interests", None),
    "Hawke's Bay Regional Council": ("www.hbrc.govt.nz", None, "https://www.hbrc.govt.nz/assets/Councillors/2024-Summary-of-HBRC-Councillors-Pecuniary-Interests.pdf"),
    "Horowhenua District Council": ("www.horowhenua.govt.nz", None, "https://www.horowhenua.govt.nz/files/assets/public/v/4/council/2022-2025/february-2026-register-of-elected-member-pecuniary-interests.pdf"),
    "Hurunui District Council": ("www.hurunui.govt.nz", "https://www.hurunui.govt.nz/council/mayor-councillors", None),
    "Hutt City Council": ("www.huttcity.govt.nz", "https://www.huttcity.govt.nz/council/meet-your-council", None),
    "Invercargill City Council": ("www.icc.govt.nz", "https://www.icc.govt.nz/council/about-council/01-governance/interest-register", None),
    "Kaikoura District Council": ("www.kaikoura.govt.nz", "https://www.kaikoura.govt.nz/council/mayor-councillors", None),
    "Kaipara District Council": ("www.kaipara.govt.nz", "https://www.kaipara.govt.nz/council/Mayor-and-councillors-5", "https://www.kaipara.govt.nz/uploads/governance/KDC%20Members%20Interests%20at%20February%202026.pdf"),
    "Kapiti Coast District Council": ("www.kapiticoast.govt.nz", "https://www.kapiticoast.govt.nz/council/about-council/the-role-of-council/declarations-of-interest/", "https://www.kapiticoast.govt.nz/media/310j5olm/register-of-interests-2026.pdf"),
    "Kawerau District Council": ("www.kaweraudc.govt.nz", None, None),
    "Mackenzie District Council": ("www.mackenzie.govt.nz", "https://www.mackenzie.govt.nz/council/mayor-and-councillors", None),
    "Manawatu-Wanganui Regional Council": ("www.horizons.govt.nz", "https://www.horizons.govt.nz/your-council/councillors", None),
    "Manawatu District Council": ("www.mdc.govt.nz", None, "https://www.mdc.govt.nz/__data/assets/pdf_file/0020/205409/Elected-Members-Pecuniary-Interests-2025-26-Public-Summary.pdf"),
    "Marlborough District Council": ("www.marlborough.govt.nz", None, "https://www.marlborough.govt.nz/repository/libraries/id:2ifzri1o01cxbymxkvwz/hierarchy/documents/your-council/mission-statement-list/Elected_Members_Interests_Public_Register_2022-25.pdf"),
    "Masterton District Council": ("www.mstn.govt.nz", "https://www.mstn.govt.nz/council/meetings/local-governance-statement", None),
    "Matamata-Piako District Council": ("www.mpdc.govt.nz", "https://mpdc.govt.nz/councillors-mayor/councillor-declarations-of-interests", None),
    "Napier City Council": ("www.napier.govt.nz", "https://www.napier.govt.nz/our-council/mayor-and-councillors/", "https://www.napier.govt.nz/assets/Uploads/2025-DOI-Register.pdf"),
    "Nelson City Council": ("www.nelson.govt.nz", None, "https://www.nelson.govt.nz/repository/libraries/id:2r883m1me1cxbyryo0mp/hierarchy/1Your%20Council/About/Governance%20Information/Summary%20of%20Pecuniary%20Interests%20%28updated%20as%20of%2030%20Jul%202026%29.pdf"),
    "New Plymouth District Council": ("www.npdc.govt.nz", "https://www.npdc.govt.nz/council/about-the-council/register-of-member-s-pecuniary-interests", None),
    "Northland Regional Council": ("www.nrc.govt.nz", "https://www.nrc.govt.nz/your-council/elected-members/register-of-pecuniary-interests/", None),
    "Opotiki District Council": ("www.odc.govt.nz", None, None),
    "Otago Regional Council": ("www.orc.govt.nz", "https://www.orc.govt.nz/your-council/public-reporting/register-of-members-pecuniary-interests/", "https://www.orc.govt.nz/media/xhwfqlzz/20260721-register-of-pecuniary-interests.pdf"),
    "Otorohanga District Council": ("otodc.govt.nz", None, "https://otodc.govt.nz/assets/Documents/Other/Register-of-Members-Pecuinary-Interests-June-2024.pdf"),
    "Palmerston North City Council": ("www.pncc.govt.nz", "https://www.pncc.govt.nz/Council/Document-library/Governance-publications/Register-of-members-pecuniary-interests", None),
    "Porirua City Council": ("poriruacity.govt.nz", "https://poriruacity.govt.nz/your-council/mayor-councillors/what-your-council-does/", None),
    "Queenstown-Lakes District Council": ("www.qldc.govt.nz", "https://www.qldc.govt.nz/your-council/elected-members/register-of-interests/", "https://www.qldc.govt.nz/media/5qgdcm2x/2026-register-of-interests-summary.pdf"),
    "Rangitikei District Council": ("www.rangitikei.govt.nz", "https://www.rangitikei.govt.nz/council/mayor-councillors/governance-documents/register-of-members-pecuniary-interests", None),
    "Rotorua Lakes Council": ("www.rotorualakescouncil.nz", "https://www.rotorualakescouncil.nz/our-council/news/news?item=id:2q85khsw61cxbyn8wwse", None),
    "Ruapehu District Council": ("www.ruapehudc.govt.nz", "https://www.ruapehudc.govt.nz/our-council/about-our-council/governance-statement/zregister-of-members-pecuniary-interests", None),
    "Selwyn District Council": ("www.selwyn.govt.nz", "https://www.selwyn.govt.nz/your-council/mayor-And-council/meet-your-mayor-and-councilors", None),
    "South Taranaki District Council": ("www.southtaranaki.com", "https://www.southtaranaki.com/our-council/governance/pecuniary-interests-register", None),
    "South Waikato District Council": ("www.southwaikato.govt.nz", "https://www.southwaikato.govt.nz/our-council/mayor-and-councillors", None),
    "South Wairarapa District Council": ("swdc.govt.nz", "https://swdc.govt.nz/your-council/council-profile/", None),
    "Southland District Council": ("www.southlanddc.govt.nz", "https://www.southlanddc.govt.nz/council/role-of-council/governance/", None),
    "Southland Regional Council": ("www.es.govt.nz", "https://www.es.govt.nz/about-us/about-council/councillors/meet-your-councillors", None),
    "Stratford District Council": ("www.stratford.govt.nz", None, "https://www.stratford.govt.nz/repository/libraries/id:2cvuccagl1cxbygm8445/hierarchy/Governance/Summary%20-%20Pecuniary%20Interest%20Summary%20-%20May%202026.pdf"),
    "Taranaki Regional Council": ("www.trc.govt.nz", "https://www.trc.govt.nz/council/council-and-region/elected-councillors", "https://trc.govt.nz/assets/Documents/Plans-policies/2025-Councillor-Pecuniary-Interest-Disclosure.pdf"),
    "Tararua District Council": ("www.tararuadc.govt.nz", "https://www.tararuadc.govt.nz/your-council/council-contacts/register-of-pecuniary-interests-of-elected-members", None),
    "Tasman District Council": ("www.tasman.govt.nz", "https://www.tasman.govt.nz/my-council/about-us/your-mayor-and-councillors/elected-and-appointed-members-interests", None),
    "Taupo District Council": ("www.taupodc.govt.nz", "https://www.taupodc.govt.nz/council/mayor-and-councillors", None),
    "Tauranga City Council": ("www.tauranga.govt.nz", "https://www.tauranga.govt.nz/council/how-the-council-works/governance/code-of-conduct-and-members-interests/mayor-and-councillors-register-of-interests", None),
    "Thames-Coromandel District Council": ("www.tcdc.govt.nz", None, "https://www.tcdc.govt.nz/files/assets/public/v/1/our-council/about-our-council/governance-documents/register-of-pecuniary-and-other-specified-interests-30-mar-2026.pdf"),
    "Timaru District Council": ("www.timaru.govt.nz", "https://www.timaru.govt.nz/council/elected-council-members", "https://www.timaru.govt.nz/__data/assets/pdf_file/0008/728963/Members-Interests-2025-2028.pdf"),
    "Upper Hutt City Council": ("www.upperhutt.govt.nz", "https://www.upperhutt.govt.nz/council/about-your-council/elected-members-elt", None),
    "Waikato District Council": ("www.waikatodistrict.govt.nz", "https://www.waikatodistrict.govt.nz/your-council/people/mayor-and-councillors", None),
    "Waikato Regional Council": ("www.waikatoregion.govt.nz", "https://www.waikatoregion.govt.nz/council/about-us/councillors/interests-registers/", None),
    "Waimakariri District Council": ("www.waimakariri.govt.nz", "https://waimakariri.govt.nz/your-council/council-boards-and-committees/mayor-and-councillors", None),
    "Waimate District Council": ("www.waimatedc.govt.nz", "https://www.waimatedc.govt.nz/council/about-council", None),
    "Waipa District Council": ("www.waipadc.govt.nz", "https://www.waipadc.govt.nz/our-council/our-team/mayor-and-councillors", None),
    "Wairoa District Council": ("www.wairoadc.govt.nz", "https://www.wairoadc.govt.nz/our-council/mayor-and-councillors/", None),
    "Waitaki District Council": ("www.waitaki.govt.nz", "https://www.waitaki.govt.nz/Council/About-our-Council/Our-elected-members/Mayor-and-councillors", None),
    "Waitomo District Council": ("www.waitomo.govt.nz", None, "https://www.waitomo.govt.nz/media/3n0fwji1/register-of-elected-members-interests-2026-updated-may-2026.pdf"),
    "Wellington City Council": ("wellington.govt.nz", "https://wellington.govt.nz/your-council/about-the-council/mayor-and-councillors/register-of-pecuniary-interests", None),
    "Wellington Regional Council": ("www.gw.govt.nz", "https://www.gw.govt.nz/your-council/council-and-councillors/meet-the-councillors/elected-members-register-of-interests/elected-members-statutory-returns-of-pecuniary-interests/", None),
    "West Coast Regional Council": ("www.wcrc.govt.nz", "https://www.wcrc.govt.nz/council/your-councillors", None),
    "Western Bay of Plenty District Council": ("www.westernbay.govt.nz", None, "https://www.westernbay.govt.nz/repository/libraries/id:25p4fe6mo17q9stw0v5w/hierarchy/council/about-the-council/documents/Councillor%20Pecuniary%20and%20Non%20Pecuniary%20Interests%20-%202025-2026%20-%20Register%20-%20Redacted.pdf"),
    "Westland District Council": ("www.westlanddc.govt.nz", "https://www.westlanddc.govt.nz/your-council/mayor-and-councillors/", None),
    "Whakatane District Council": ("www.whakatane.govt.nz", "https://whakatane.govt.nz/about-council/council-people/mayor-and-councillors-profiles", None),
    "Whanganui District Council": ("www.whanganui.govt.nz", "https://www.whanganui.govt.nz/Your-Council/Your-Elected-Members/Register-of-members%E2%80%99-pecuniary-interests", None),
    "Whangarei District Council": ("www.wdc.govt.nz", "https://www.wdc.govt.nz/Council/Governance/Elected-members", "https://www.wdc.govt.nz/files/assets/public/v/4/documents/council/governance/register-of-pecuniary-interests-elected-members.pdf"),
}


# ── pure pieces ───────────────────────────────────────────────────────────────

def off_peak(t: dt.datetime) -> bool:
    h = t.astimezone(NZ).hour
    return h >= OFF_PEAK[0] or h < OFF_PEAK[1]


def table(schema: str, t: str) -> str:
    return f"{schema}.{t}" if schema == SCHEMA else f"{schema}.{SCHEMA}_{t}"


def capture_sql(schema: str = SCHEMA) -> str:
    with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
        text = f.read().split(READING)[0]
    pre = "" if schema == SCHEMA else f"{SCHEMA}_"
    return re.sub(rf"(?<![A-Za-z0-9_]){SCHEMA}\.", f"{schema}.{pre}", text)


def site_of(host: str) -> str:
    return host.lower().removeprefix("www.")


def on_site(url: str, host: str) -> bool:
    h = fg.host_of(url)
    return h == host or site_of(h) == site_of(host) or h.endswith("." + site_of(host))


def clean_url(url: str) -> str:
    """An address as a browser sends it: control characters dropped, spaces and other unsafe characters
    percent-encoded (three councils link files by names with spaces, line breaks or macrons)."""
    url = re.sub(r"[\x00-\x1f\x7f]", "", url).strip()
    p = urllib.parse.urlsplit(url)
    safe = "/%:@!$&'()*+,;=-._~"
    return urllib.parse.urlunsplit((p.scheme, p.netloc, urllib.parse.quote(p.path, safe=safe),
                                    urllib.parse.quote(p.query, safe=safe + "?"), ""))


def register_links(body: bytes, page_url: str, host: str) -> list:
    """The links on a page, on the council's own site, that name the register by address or words, each once:
    [(url, 'document' | 'page')]. Relative links resolve against the page's own `<base href>` where it has one."""
    page = body.decode("utf-8", "replace")
    base = re.search(r"<base\b[^>]*href=[\"']([^\"']+)", page, re.I)
    page_url = urllib.parse.urljoin(page_url, html.unescape(base.group(1))) if base else page_url
    out, seen = [], set()
    for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", page, re.S | re.I):
        href, words = html.unescape(m.group(1)).strip(), re.sub(r"<[^>]+>", " ", m.group(2))
        if href.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        url = clean_url(urllib.parse.urljoin(page_url, href))
        if url in seen or url.rstrip("/") == page_url.rstrip("/") or not on_site(url, host):
            continue
        if not (REGISTER_LINK.search(urllib.parse.unquote(url)) or REGISTER_LINK.search(html.unescape(words))):
            continue
        seen.add(url)
        out.append((url, "document" if DOC.search(url) else "page"))
    return out


def capture_same_site(a: str, b: str) -> bool:
    return site_of(fg.host_of(a)) == site_of(fg.host_of(b))


def capture_site_held(url: str, held: dict) -> bool:
    return site_of(fg.host_of(url)) in {site_of(h) for h in held}


# ── the lane's capture tables ─────────────────────────────────────────────────

class Tables:
    def __init__(self, conn, schema: str = SCHEMA):
        self.conn, self.s = conn, schema
        self.T = lambda t: table(schema, t)

    def create(self):
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.s}")
        self.conn.execute(capture_sql(self.s))

    def try_lock(self) -> bool:
        return bool(self.conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (JOB,)).fetchone()[0])

    def held_hosts(self) -> dict:
        return dict(self.conn.execute(f"SELECT host, why FROM {self.T('capture_held_hosts')}").fetchall())

    def hold(self, host, why):
        self.conn.execute(f"INSERT INTO {self.T('capture_held_hosts')} (host, why) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                          (host, why[:500]))
        self.set_aside(host, "host", why)

    def last_asked(self, url):
        """When the url was last asked, and whether a document was landed from it; a request that never left the box
        (a malformed address) is not an ask. A document asked and not landed (a 404, a redirect) is asked again monthly
        (2 November 2026: five councils' addresses had failed once and were never asked again)."""
        r = self.conn.execute(f"SELECT max(asked_at), bool_or(kind = 'document' AND sha256 IS NOT NULL) FROM {self.T('capture_items')} "
                              "WHERE url = %s AND coalesce(why, '') NOT LIKE %s", (url, NOT_SENT + "%")).fetchone()
        return r if r else (None, None)

    def newest_sha(self, url):
        r = self.conn.execute(f"SELECT sha256 FROM {self.T('capture_items')} WHERE url = %s AND sha256 IS NOT NULL "
                              "ORDER BY asked_at DESC, item_id DESC LIMIT 1", (url,)).fetchone()
        return r[0] if r else None

    def item(self, council, url, kind, found_on, status, sha, why):
        self.conn.execute(f"INSERT INTO {self.T('capture_items')} (council, url, kind, found_on, status, sha256, why) "
                          "VALUES (%s, %s, %s, %s, %s, %s, %s)", (council, url, kind, found_on, status, sha, why))

    def set_aside(self, item, stage, reason):
        self.conn.execute(f"INSERT INTO {self.T('capture_set_aside')} (item, stage, reason) VALUES (%s, %s, %s)",
                          (str(item), stage, reason[:500]))


# ── a run ─────────────────────────────────────────────────────────────────────

class Run:
    def __init__(self, tables, *, land_fn, opener=None, clock=None, sleep=None, now=None, registers: dict = None,
                 budget_s: float = DEFAULT_BUDGET_S, anytime: bool = False, log=print, gate_held=None):
        self.t, self.land_fn, self.log = tables, land_fn, log
        # the gate's hold on a host (ruling 141); an injected opener is a test's site, never the live ledger's host
        self.gate_held = gate_held or (fg.refused_by if opener is None else (lambda host: None))
        self.opener = opener or (lambda url, timeout: fg.open_url(url, timeout=timeout, positions_dir=POSITIONS,
                                                                  max_bytes=50_000_000))
        self.clock = clock or time.monotonic
        self.pacer = fg.Pacer(now=self.clock, sleep=sleep or time.sleep)
        self.now = now or (lambda: dt.datetime.now(NZ))
        self.registers = registers if registers is not None else REGISTERS
        self.budget_s, self.anytime = budget_s, anytime
        self.started = self.clock()
        self.counts = {"requests": 0, "pages": 0, "documents": 0, "already_held": 0, "failed": 0, "held_hosts": 0}
        self.stopped = ""

    def time_left(self) -> bool:
        if self.clock() - self.started >= self.budget_s:
            self.stopped = self.stopped or "budget spent"
            return False
        if not self.anytime and not off_peak(self.now()):
            self.stopped = self.stopped or "off-peak is over"
            return False
        return True

    def due(self, url, kind) -> bool:
        at, landed_doc = self.t.last_asked(url)
        if at is None:
            return True
        if landed_doc:
            return False                                   # a document landed is asked once; one that failed, monthly
        return (dt.datetime.now(dt.timezone.utc) - at).days >= EVERY_DAYS

    def ask(self, council, url, kind, found_on, held, hops=0):
        host = fg.host_of(url)
        if capture_site_held(url, held) or not self.due(url, kind):
            return None
        if self.gate_held(host) is not None:
            # ruling 141: a host the gate holds is asked nothing and nothing is written: no ask is recorded (the page
            # stays due) and the lane's own hold is not taken, so the person who clears the gate clears it for the lane
            return None
        self.pacer.wait(host, FLOOR_S)
        self.counts["requests"] += 1
        why = None
        try:
            f = self.opener(url, 90)
        except fg.Refused as exc:
            f, why = None, f"refused by the gate: {str(exc)[:200]}"
        except (ValueError, UnicodeError) as exc:      # a malformed address: the request never left the box
            self.t.item(council, url, kind, found_on, None, None, f"{NOT_SENT}{type(exc).__name__}: {str(exc)[:200]}")
            self.counts["failed"] += 1
            return None
        except Exception as exc:  # noqa: BLE001
            f, why = None, f"transport: {type(exc).__name__}: {str(exc)[:200]}"
        if f is not None and f.blocked:
            why = f.blocked
        elif f is not None and f.location and capture_same_site(f.location, url) and hops < 1:
            self.t.item(council, url, kind, found_on, f.status, None, f"HTTP {f.status}: to {f.location} on the same site")
            return self.ask(council, clean_url(f.location), kind, url, held, hops + 1)
        elif f is not None and f.location and fg.host_of(f.location) in DOC_HOSTS.get(council, ()) and hops < 1:
            self.t.item(council, url, kind, found_on, f.status, None, f"HTTP {f.status}: to {f.location}, the council's own document store")
            return self.ask(council, clean_url(f.location), "document", url, held, hops + 1)
        elif f is not None and (f.status != 200 or not f.body):
            why = f"HTTP {f.status}" + (f", redirected to {f.location}: not followed" if f.location else "")
        if why:
            self.t.item(council, url, kind, found_on, getattr(f, "status", None), None, why)
            self.counts["failed"] += 1
            if f is None and not why.startswith("refused"):
                return None                             # a transport failure: the host may be in trouble, not a block
            if f is not None and not f.blocked and f.status not in SERVER_ERRORS:
                return None                             # the host answering: 404, 410, a redirect off the site
            self.t.hold(host, why)
            held[host] = why
            self.counts["held_hosts"] += 1
            return None
        is_pdf = f.body[:5] == b"%PDF-"
        ref, new = self.land_fn(f.body, name=url, content_type="application/pdf" if is_pdf else "text/html")
        kind = "document" if is_pdf or kind == "document" else "page"
        self.t.item(council, url, kind, found_on, f.status, ref.sha256, None)
        self.counts["documents" if kind == "document" else "pages"] += 1
        if not new:
            self.counts["already_held"] += 1
        return f if not is_pdf else None

    def held_body(self, url, held):
        """The newest landed copy of a page not due tonight, so the documents it links are still met; None for a
        page never landed or on a held site."""
        from support.docstore.landing import read_bytes
        if capture_site_held(url, held):
            return None
        sha = self.t.newest_sha(url)
        if not sha:
            return None
        body = read_bytes(sha)
        return None if body[:5] == b"%PDF-" else body

    def council(self, name, held):
        host, page, pdf = self.registers[name]
        linked = set()
        if page:
            f = self.ask(name, page, "page", None, held)
            body = f.body if f is not None else self.held_body(page, held)
            for url, kind in (register_links(body, page, host) if body else []):
                linked.add(url)
                if not self.time_left():
                    return
                g = self.ask(name, url, kind, page, held)
                g_body = g.body if g is not None else (self.held_body(url, held) if kind == "page" else None)
                if g_body is not None:                          # a register page one step down: its documents
                    for u2, k2 in register_links(g_body, url, host):
                        if k2 == "document" and self.time_left():
                            linked.add(u2)
                            self.ask(name, u2, k2, url, held)
        if pdf and pdf not in linked and self.time_left():
            self.ask(name, pdf, "document", None, held)

    def run(self) -> dict:
        held = self.t.held_hosts()
        for name in self.registers:
            if not self.time_left():
                break
            if name in TERMS_BAR:
                continue
            self.council(name, held)
        return {**self.counts, "stopped": self.stopped}


def outcome(out: dict):
    if out["requests"] and not (out["pages"] or out["documents"]):
        return False, (out["stopped"] or "done") + "; nothing landed"
    return True, out["stopped"] or "done"


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, content_type):
        return land(data, name=name, source=SOURCE, conn=conn, name_kind="url", content_type=content_type)
    return land_fn


# ── adopting a session's capture record ───────────────────────────────────────

ADOPT_TABLES = ('capture_items', 'capture_held_hosts', 'capture_set_aside')


def adopt(src, dst, src_schema: str, dst_schema: str = SCHEMA, log=print) -> dict:
    """Carry a session's proven capture record (its scratch schema in the sample database) into the lane's own schema
    on `dst`, once, so the first live run asks nothing the session already asked; each landed document's bytes are
    landed again on `dst` from the document store (no fetch). Refuses when the lane's record on `dst` is not empty."""
    from support.docstore.landing import land, names_of, path_for, read_bytes
    Tables(dst, dst_schema).create()
    if any(dst.execute(f"SELECT 1 FROM {table(dst_schema, t)} LIMIT 1").fetchone() for t in ADOPT_TABLES):
        raise RuntimeError(f"{SCHEMA}: the live capture record is not empty; nothing adopted")
    counts = {}
    for t in ADOPT_TABLES:
        cur = src.execute(f"SELECT * FROM {table(src_schema, t)}")
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
        with dst.cursor().copy(f"COPY {table(dst_schema, t)} ({', '.join(cols)}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
        for c in cols:                                   # a serial id copied as it was: move its sequence past it
            seq = dst.execute("SELECT pg_get_serial_sequence(%s, %s)", (table(dst_schema, t), c)).fetchone()[0]
            if seq and rows:
                dst.execute(f"SELECT setval(%s, (SELECT max({c}) FROM {table(dst_schema, t)}))", (seq,))
        counts[t] = len(rows)
    shas = set()
    for t in ADOPT_TABLES:
        cols = [r[0] for r in src.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s "
                                          "AND table_name = %s", (src_schema, table(src_schema, t).split(".", 1)[1]))]
        if "sha256" in cols:
            shas |= {r[0] for r in src.execute(f"SELECT sha256 FROM {table(src_schema, t)} WHERE sha256 IS NOT NULL")}
    landed = 0
    for sha in sorted(shas):
        if not os.path.exists(path_for(sha)):          # a hash the old estate holds, not this store: copied later
            continue
        for name in names_of(sha, src) or [sha]:
            land(read_bytes(sha), name=name, source=SOURCE, conn=dst, name_kind="url" if name.startswith("http") else "file")
        landed += 1
    counts["documents re-landed"] = landed
    for k, v in counts.items():
        log(f"{SCHEMA}: adopted {k}: {v}")
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.councillor_interests.capture")
    ap.add_argument("--anytime", action="store_true", help="outside off-peak (by hand: a proof)")
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    ap.add_argument("--only", action="append", help="a council's name, as REGISTERS has it")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    ap.add_argument("--adopt", metavar="SCRATCH_SCHEMA", help="the integrator, once: carry a session's capture record "
                    "from querynz_v4_sample into the live schema")
    a = ap.parse_args(argv)
    from support import db, jobrun
    if a.adopt:
        with db.connect(db.OWNER_KEY, "querynz_v4_sample") as src, db.connect(db.OWNER_KEY, a.database, autocommit=True) as dst:
            adopt(src, dst, a.adopt)
        return 0
    started = jobrun.now()
    regs = {k: v for k, v in REGISTERS.items() if not a.only or k in a.only}
    with db.connect(db.OWNER_KEY, a.database, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '60s'")
        t = Tables(conn, a.schema)
        t.create()
        if not t.try_lock():
            print(f"{SOURCE}: another run holds the lane; this one asks for nothing")
            return 0
        out = Run(t, land_fn=landing(conn), registers=regs, anytime=a.anytime, budget_s=a.budget_s).run()
    ok, last = outcome(out)
    detail = (f"{out['requests']} requests, {out['pages']} pages, {out['documents']} documents, {out['already_held']} "
              f"already held, {out['failed']} failed, {out['held_hosts']} hosts held; {last}")
    print(f"{SOURCE}: {detail}")
    if a.database == "querynz_v4":
        jobrun.record(JOB, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
