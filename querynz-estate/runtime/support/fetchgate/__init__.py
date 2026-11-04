"""The fetch gate: the one place a fetch's permission and pacing are decided
(plan 1.10; from the old `ingestion/fetchgate.py`, with its robots refusal
replaced as hard limit 5 says).

Capture is judged on legality and politeness (hard limit 4), and a robots
file is no longer a permission decision (hard limit 5, ruling 10). The gate
reads robots.txt for ONE thing, a stated crawl delay, and honours it; the
file is archived verbatim with its hash, as a record. What refuses:

  1. a source out by name (hard limit 8): fyi.org.nz and every NZME masthead;
     a held host is not even sent a request for its robots.txt
  2. no one-page legal position on file for the host's class of source
     (hard limit 9): `docs/legal/positions/<class>.md` names its hosts
  3. a publisher's direct request to stop (hard limit 7): `STOP_REQUESTS`
  4. a challenge or a block met on the read (hard limit 6): a 403, 429 or
     5xx, or a challenge page, is a failed read. It is logged and the lane
     moves on; nothing is solved, logged in to, or got around
  5. a host that refused or throttled us (Arthur, 3 November 2026: "when our
     connection starts getting refused or we are throttled like in the
     tenancy tribunal, stop gathering. we should consider a new way
     forward"): a 403, 429 or 503, or a challenge page, holds the host at
     once; three transport failures in a row on it (a reset, a refusal, a
     timeout, a 500, 502 or 504) hold it too. A held host is sent nothing
     more by any lane until a person clears it (`python -m support.fetchgate
     clear HOST --by NAME`); the hold and the clearing are lines in
     `<live>/checks/fetch-gate/refusals.jsonl`, never edited
  6. a redirect is not followed unasked: the gate judged the host asked,
     not the one pointed to. `open_url` returns the 3xx with its Location;
     a caller that wants it followed passes `follow=`, and every hop is
     judged, recorded and paced as a fresh request

Politeness (hard limit 7): one User-Agent for the whole estate; a floor
between requests to one host that is the SLOWEST of the default, the stated
floor, the crawl delay and the polite floor; a pacer that blocks and is keyed
by host, so an exit rotation never buys speed; low concurrency; nothing
fetched twice (the document store's sameness hash). An unreadable robots
file is not a refusal; it means the host may be in trouble, so the polite
floor applies.

Every decision is recorded, with its reason, in `<live>/checks/fetch-gate/`.
Pure where it can be: `decide()` takes what was read and returns a decision
with no network, no clock, no file. Stdlib only.
"""
import datetime as dt
import hashlib
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import asdict, dataclass, field

LIVE = os.environ.get("QV4_LIVE") or "/home/user/querynzv4-work/live"
LEDGER_DIR = os.path.join(LIVE, "checks", "fetch-gate")
ROBOTS_DIR = os.path.join(LIVE, "checks", "robots")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POSITIONS_DIR = os.environ.get("QV4_POSITIONS") or os.path.join(REPO, "docs", "legal", "positions")

#: the one User-Agent. A string that appears twice is a string that differs once.
UA = "QueryNZ/1.0 (research aggregator; contact: admin@followthemoney.nz)"
OUR_TOKEN = "QueryNZ"
DEFAULT_FLOOR_S = 1.5
POLITE_FLOOR_S = 5.0
MAX_FLOOR_S = 120.0          # a crawl delay above this is honoured at this: the host is asking not to be crawled
CHALLENGE_STATUSES = (403, 429, 503, 502, 500, 504)
#: a refusal or a throttle: the host is held at the first one
HOLD_STATUSES = (403, 429, 503)
#: transport failures (and the other 5xx) in a row on one host that hold it
HOLD_STRIKES = 3
REFUSALS_FILE = "refusals.jsonl"
CHALLENGE_MARKS = ("cf-chl", "challenge-platform", "just a moment", "attention required", "captcha",
                   "radware", "incapsula", "_incapsula_", "are you a human", "access denied",
                   "pardon our interruption")
#: response headers only a challenge or block page carries (lower case)
CHALLENGE_HEADERS = ("x-spa-interstitial",)    # Imperva's interstitial (grants-1, 21 October)
#: the most a challenge or block page weighs. Cloudflare's "Just a moment..." shell is 29,045 bytes (old lesson:
#: a shell outweighs a short article, so size alone never clears a page with a block's title); Christchurch's
#: InfoCouncil listing, 795,737 bytes with 237 minutes links and "captcha" in a form's script, is content (councils-1)
CHALLENGE_PAGE_MAX = 64 * 1024
REDIRECT_STATUSES = (301, 302, 303, 307, 308)

#: hosts we do not capture from (hard limit 8). Matched with every parent domain.
HELD = {
    "fyi.org.nz": "ruling 321: fyi.org.nz is not captured, indexed or read (hard limit 8)",
    "nzherald.co.nz": "ruling 12: NZME is not captured, indexed or read (hard limit 8)",
    "businessdesk.co.nz": "ruling 12: NZME (BusinessDesk is NZME-owned)",
    "newstalkzb.co.nz": "ruling 12: NZME",
    "gisborneherald.co.nz": "ruling 12: NZME",
    "oneroof.co.nz": "ruling 12: NZME",
    "driven.co.nz": "ruling 12: NZME",
    "nzme.co.nz": "ruling 12: NZME",
    "hansard.parliament.nz": "ruling 78: Hansard is not captured by the estate (a challenge since about 5 October 2026); its register comes from the old export and the MCP (ruling 96)",
    "parliament.nz": "ruling 78: not captured by the estate; the MCP is the source (rulings 94, 96)",
}
#: a publisher's direct request to stop: host → when and how it was made (hard limit 7)
STOP_REQUESTS = {}
#: stated floors (seconds between requests), one table, one home
FLOORS = {
    "web.archive.org": 1.0,
    "www.odata.charities.govt.nz": 5.0,   # the Charities Register's feed (charities-capture-1, 20 October)
    "api.business.govt.nz": 5.0,          # the NZBN register's entity detail (societies-1, 20 October)
    "ideas.repec.org": 5.0,
    "greaterauckland.org.nz": 30.0,
    "farmersweekly.co.nz": 5.0,
    "publicdata.co.nz": 5.0,
    # track E, the windowed sources: the floor each legal position states
    # (docs/legal/positions/tenancy-tribunal-decisions.md, real-estate-authority-decisions.md)
    "forms.justice.govt.nz": 5.0,
    "decisions.dotnous.com": 5.0,
    # step 5.3 (sanctions-1, 21 October): the Board's decisions list; the two held lists, should they ever be authorised
    "www.lbp.govt.nz": 5.0,
    "www.police.govt.nz": 10.0,
    "scsanctions.un.org": 10.0,
    "catalogue.data.govt.nz": 10.0,   # its own crawl delay (tenders-1, 21 October)
    # step 5.3, the regulator lanes (regulators-1, 21 October)
    "www.comcom.govt.nz": 5.0,
    "www.fma.govt.nz": 5.0,
    "www.worksafe.govt.nz": 5.0,
    "www.linz.govt.nz": 5.0,   # the overseas investment decisions (oio-1, 21 October)
    "www.communitymatters.govt.nz": 5.0,   # the Lottery's records of grants (grants-1, 21 October)
    "www.dia.govt.nz": 5.0,   # the Department's class 4 list (grants-1, 21 October)
    "airrescueservices.co.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "pelorustrust.net.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "agt.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "onefoundation.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "trustaoraki.co.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "newhorizoncommunitytrust.co.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "milestonefoundation.co.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "wecare.org.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "nzct.org.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "growregions.govt.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "tec.govt.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "educationcounts.govt.nz": 5.0,   # grants-2 (22 October): the class A societies' own lists; regional and tertiary funding surveyed
    "www.tkm.govt.nz": 5.0,   # Te Kāhui Māngai, the iwi and hapū directory (settlements-1, 22 October)
    "tehaeata.govt.nz": 5.0,   # Te Haeata, behind a login: watched, one request a week (settlements-1, 22 October)
    "www.cluthadc.govt.nz": 7.0,   # the council asks 7 s; its terms page watched monthly (procurement-1, 22 October)
    "www.tauranga.govt.nz": 5.0,   # terms page watched monthly (procurement-1, 22 October)
    "www.dunedin.govt.nz": 5.0,   # terms page watched monthly (procurement-1, 22 October)
    "www.vendorpanel.nz": 5.0,   # the platform's terms page watched monthly (procurement-1, 22 October)
    "infocouncil.biz": 5.0,   # InfoCouncil meeting listings and minutes (councils-1, 23 October)
    "infocouncil.fndc.govt.nz": 5.0,   # InfoCouncil meeting listings and minutes (councils-1, 23 October)
    "infocouncil.tauranga.govt.nz": 5.0,   # InfoCouncil meeting listings and minutes (councils-1, 23 October)
    "infocouncil.dunedin.govt.nz": 5.0,   # InfoCouncil meeting listings and minutes (councils-1, 23 October)
    "infocouncil.boprc.govt.nz": 5.0,   # InfoCouncil meeting listings and minutes (councils-1, 23 October)
    "hamilton.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "swdc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.boprc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.chbdc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.fndc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.gdc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.goredc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.gw.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.hastingsdc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.hbrc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.horizons.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.horowhenua.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.huttcity.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.kaikoura.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.kaipara.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.kapiticoast.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.kaweraudc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.marlborough.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.mdc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.napier.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.nelson.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.npdc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.nrc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.orc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.otodc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.pncc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.rangitikei.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.rotorualakescouncil.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.selwyn.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.taupodc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.tcdc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.trc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.waimatedc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.waipadc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.wairoadc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.waitaki.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.waitomo.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.wcrc.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.whakatane.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "www.whanganui.govt.nz": 5.0,   # local election candidate returns (local-elections-1, 23 October)
    "hccpublicdocs.azurewebsites.net": 5.0,   # local election candidate returns (local-elections-1, 23 October)
}


class Refused(RuntimeError):
    """A permission decision, raised. Never caught and retried."""


@dataclass
class Robots:
    """What the host's robots.txt said when we read it: a record and a
    crawl delay, never a permission."""
    host: str
    text: str
    status: int          # 0 when nothing answered
    unreadable: bool     # 5xx, 429, timeout, DNS: the host could not answer
    crawl_delay: float
    read_at: str
    sha256: str


@dataclass
class Decision:
    allowed: bool
    reason: str
    host: str
    url: str
    floor: float
    position: str        # the class of source the position on file covers, or ''
    read_at: str = ""


def host_of(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def _parents(host: str):
    parts = (host or "").lower().split(".")
    yield host.lower()
    for i in range(1, len(parts) - 1):
        yield ".".join(parts[i:])


def held_reason(host: str):
    for h in _parents(host):
        if h in HELD:
            return HELD[h]
    return None


def stop_request(host: str):
    for h in _parents(host):
        if h in STOP_REQUESTS:
            return STOP_REQUESTS[h]
    return None


def stated_floor(host: str):
    for h in _parents(host):
        if h in FLOORS:
            return FLOORS[h]
    return None


def positions(folder: str = None) -> dict:
    """host → class of source, from the `hosts:` line of every position on
    file. A position is `docs/legal/positions/<class>.md` with a `hosts:`
    line naming the hosts it covers, comma-separated."""
    folder = folder or POSITIONS_DIR
    out = {}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".md") or n == "README.md":
            continue
        try:
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        m = re.search(r"^hosts:\s*(.+)$", text, re.M)
        if not m:
            continue
        for h in m.group(1).split(","):
            h = h.strip().lower()
            if h:
                out[h] = n[:-3]
    return out


def position_for(host: str, folder: str = None):
    pos = positions(folder)
    for h in _parents(host):
        if h in pos:
            return pos[h]
    return None


def floor_for(host: str, robots: Robots = None) -> float:
    """The slowest of every floor that applies; never a caller's own number."""
    cands = [DEFAULT_FLOOR_S]
    if (s := stated_floor(host)) is not None:
        cands.append(s)
    if robots is not None:
        if robots.crawl_delay:
            cands.append(min(float(robots.crawl_delay), MAX_FLOOR_S))
        if robots.unreadable:
            cands.append(POLITE_FLOOR_S)
    return max(cands)


def crawl_delay_of(text: str) -> float:
    """The one sanctioned use of the standard robots parser: Crawl-delay is a
    directive read per group, not a path decision."""
    rp = urllib.robotparser.RobotFileParser()
    rp.parse((text or "").splitlines())
    d = rp.crawl_delay(OUR_TOKEN)
    if d is None:
        d = rp.crawl_delay("*")
    try:
        return float(d) if d is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def decide(url: str, robots: Robots = None, position: str = None) -> Decision:
    """Pure. The decision for one URL, with the reason it was made."""
    host = host_of(url)
    floor = floor_for(host, robots)
    read_at = robots.read_at if robots else ""

    def d(allowed, reason):
        return Decision(allowed, reason, host, url, floor, position or "", read_at)

    if not host:
        return d(False, f"not a URL with a host: {url!r}")
    if (why := held_reason(host)) is not None:
        return d(False, f"we do not capture from {host}: {why}")
    if (req := stop_request(host)) is not None:
        return d(False, f"{host} asked us to stop: {req} (hard limit 7)")
    if not position:
        return d(False, f"no one-page legal position on file for {host} (hard limit 9): write docs/legal/positions/<class>.md naming it")
    if robots is not None and robots.unreadable:
        return d(True, f"permitted under the position `{position}`; robots.txt could not be read, so the polite floor applies ({floor:.0f}s)")
    return d(True, f"permitted under the position `{position}`; floor {floor:.1f}s" + (f" (crawl delay {robots.crawl_delay:.0f}s honoured)" if robots and robots.crawl_delay else ""))


def record(decision: Decision, ledger_dir: str = None) -> None:
    ledger_dir = ledger_dir or LEDGER_DIR
    os.makedirs(ledger_dir, exist_ok=True)
    row = asdict(decision)
    row["at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with open(os.path.join(ledger_dir, dt.datetime.now().strftime("%Y-%m") + ".jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


class Pacer:
    """Per-host spacing that blocks. The slot is claimed before the wait, so
    two concurrent callers queue instead of both going at once. Keyed by
    host and nothing else: an exit rotation never resets it."""

    def __init__(self, now=None, sleep=None):
        self.now = now or time.monotonic
        self.sleep = sleep or time.sleep
        self._last = {}
        self._lock = threading.Lock()

    def reserve(self, host: str, floor: float) -> float:
        with self._lock:
            now = self.now()
            last = self._last.get(host)
            start = now if last is None else max(now, last + floor)
            self._last[host] = start
            return max(0.0, start - now)

    def wait(self, host: str, floor: float) -> float:
        gap = self.reserve(host, floor)
        if gap > 0:
            self.sleep(gap)
        return gap


_PACER = Pacer()
_ROBOTS = {}


def _fetch(url: str, timeout: int):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(1 << 20)
    except urllib.error.HTTPError as e:
        return e.code, b""


def read_robots(host: str, fetch=None, timeout: int = 20, archive_dir: str = None) -> Robots:
    """Read https://<host>/robots.txt with the one UA, archive it verbatim
    with its hash, and return the record. `fetch(url, timeout) -> (status,
    body)` is injectable; a transport error is 'unreadable'."""
    read_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        status, body = (fetch or _fetch)(f"https://{host}/robots.txt", timeout)
    except Exception:  # noqa: BLE001 — the record of a failed read is the record
        return Robots(host, "", 0, True, 0.0, read_at, "")
    if status >= 500 or status == 429:
        return Robots(host, "", status, True, 0.0, read_at, "")
    text = body.decode("utf-8", "replace") if status == 200 else ""
    sha = hashlib.sha256(body).hexdigest() if status == 200 else ""
    if status == 200:
        archive_dir = archive_dir or ROBOTS_DIR
        os.makedirs(archive_dir, exist_ok=True)
        with open(os.path.join(archive_dir, f"{host}.{sha[:12]}.txt"), "wb") as f:
            f.write(body)
    return Robots(host, text, status, False, crawl_delay_of(text), read_at, sha)


def robots_for(host: str, fetch=None, refresh: bool = False) -> Robots:
    if refresh or host not in _ROBOTS:
        _ROBOTS[host] = read_robots(host, fetch=fetch)
    return _ROBOTS[host]


# --- the hosts that refused or throttled us ------------------------------------------------------------------------

_STRIKES = {}
_LOCK = threading.Lock()


def _refusals_path(ledger_dir: str = None) -> str:
    return os.path.join(ledger_dir or LEDGER_DIR, REFUSALS_FILE)


def refusals(ledger_dir: str = None) -> dict:
    """host → the line that holds it, for every host whose last line is a hold."""
    out = {}
    try:
        with open(_refusals_path(ledger_dir), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    if row.get("state") == "held":
                        out[row["host"]] = row
                    else:
                        out.pop(row["host"], None)
    except OSError:
        pass
    return out


def refused_by(host: str, ledger_dir: str = None):
    """Why the host is held, or None."""
    row = refusals(ledger_dir).get((host or "").lower())
    return None if row is None else f"held since {row['at']}: {row['why']}"


def _line(host: str, state: str, why: str, by: str, ledger_dir: str = None) -> dict:
    row = {"host": host.lower(), "state": state, "why": why, "by": by,
           "at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    os.makedirs(ledger_dir or LEDGER_DIR, exist_ok=True)
    with open(_refusals_path(ledger_dir), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def hold(host: str, why: str, by: str = "fetch gate", ledger_dir: str = None) -> dict:
    if refused_by(host, ledger_dir) is not None:
        return refusals(ledger_dir)[host.lower()]
    return _line(host, "held", why, by, ledger_dir)


def clear(host: str, by: str, why: str = "cleared", ledger_dir: str = None) -> dict:
    """A person's word: the host may be asked again."""
    if not by:
        raise ValueError("a clearing says who gave the word")
    with _LOCK:
        _STRIKES.pop(host.lower(), None)
    return _line(host, "cleared", why, by, ledger_dir)


def _strike(host: str, why: str, ledger_dir: str = None, persist: bool = True):
    """One transport failure or a 5xx other than 503; HOLD_STRIKES in a row hold the host."""
    with _LOCK:
        n = _STRIKES[host] = _STRIKES.get(host, 0) + 1
    if n >= HOLD_STRIKES and persist:
        hold(host, f"{n} transport failures in a row, the last {why}", ledger_dir=ledger_dir)


def _answered(host: str):
    with _LOCK:
        _STRIKES.pop(host, None)


def check(url: str, *, fetch=None, positions_dir: str = None, ledger_dir: str = None) -> Decision:
    """Permission for one URL: decide, record, raise on a refusal. A held
    host is refused before its robots.txt is read: not capturing is not
    knocking."""
    host = host_of(url)
    if (why := refused_by(host, ledger_dir)) is not None:
        dec = Decision(url=url, host=host, allowed=False, floor=0.0, position="",
                       reason=f"the host refused or throttled us and is held ({why}); nothing more is asked of it until a "
                              f"person clears it: consider a new way forward (Arthur, 3 November 2026)")
        record(dec, ledger_dir)
        raise Refused(f"{url}: {dec.reason}")
    pos = position_for(host, positions_dir)
    if held_reason(host) is not None or stop_request(host) is not None or not pos:
        dec = decide(url, None, pos)
    else:
        dec = decide(url, robots_for(host, fetch=fetch), pos)
    record(dec, ledger_dir)
    if not dec.allowed:
        raise Refused(f"{url}: {dec.reason}")
    return dec


@dataclass
class Fetched:
    url: str
    status: int
    body: bytes
    final_url: str           # the address that answered: never one the gate did not judge
    blocked: str = ""        # '' or why this is a failed read (a challenge or a block)
    location: str = ""       # a 3xx's Location, absolute and NOT fetched; '' otherwise
    headers: dict = field(default_factory=dict)   # the answer's response headers, names as sent (an ETag to keep)

    @property
    def unchanged(self) -> bool:
        """A 304: the host says what we hold (sent as If-None-Match) is current. No body; not a block."""
        return self.status == 304


def looks_challenged(status: int, body: bytes, headers: dict = None) -> str:
    """A page is a challenge when its status, its own header or its title says so, or when a body no bigger than a
    challenge page carries a block's mark near its top; a word or a script name on a bigger page, which carries the
    content asked for, never makes it one (real pages from a protected site carry that script too). A 304 is the
    host saying "unchanged", not a block."""
    if status == 304:
        return ""
    if status in CHALLENGE_STATUSES:
        return f"HTTP {status}: a block or a challenge; a challenged read is a failed read (hard limit 6)"
    for name in (headers or {}):
        if name.lower() in CHALLENGE_HEADERS:
            return f"a challenge page (header {name}); a challenged read is a failed read (hard limit 6)"
    body = body or b""
    m = re.search(rb"<title[^>]*>(.*?)</title", body[:CHALLENGE_PAGE_MAX], re.I | re.S)
    title = m.group(1).decode("utf-8", "replace").lower() if m else ""
    for mark in CHALLENGE_MARKS:
        if mark in title:
            return f"a challenge page (title {mark!r}); a challenged read is a failed read (hard limit 6)"
    if len(body) > CHALLENGE_PAGE_MAX:
        return ""
    head = body[:4096].decode("utf-8", "replace").lower()
    for mark in CHALLENGE_MARKS:
        if mark in head:
            return f"a challenge page ({mark!r}); a challenged read is a failed read (hard limit 6)"
    return ""


class _NoFollow(urllib.request.HTTPRedirectHandler):
    """urllib follows a 3xx by itself; this hands it back as an HTTPError."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoFollow)


def _go(url: str, timeout: int, headers: dict, max_bytes: int):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, (r.read(max_bytes) if max_bytes else r.read()), url, dict(r.headers.items())
    except urllib.error.HTTPError as e:
        return e.code, b"", url, dict(e.headers.items()) if e.headers else {}


def open_url(url: str, *, timeout: int = 30, headers: dict = None, pacer: Pacer = None, max_bytes: int = None,
             fetch=None, positions_dir: str = None, ledger_dir: str = None, follow: int = 0,
             same_host_hops: int = 3) -> Fetched:
    """The gated fetch: check, pace, go, with the one UA. A 404 is the host
    answering; a 403, 429, 5xx or a challenge page is a failed read, returned
    as `blocked` and never retried in the same run.

    A redirect is returned, not followed: `status` is the 3xx, `location` the
    address it points to, unfetched, and `final_url` the URL asked. With
    `follow=n` up to n hops are taken, each one checked against the positions
    (a Refused is raised as for any URL), recorded and paced on its own host.
    A redirect that stays on the host asked is followed without asking, up to
    `same_host_hops` (the host was judged; http to https and a trailing slash
    are the common cases); set it to 0 to see those too.
    The answer's headers come back on `headers`, so a lane can keep an ETag
    and send it as If-None-Match; a 304 then comes back `unchanged`, no body.
    `fetch(url, timeout) -> (status, body, final[, headers])` is injectable."""
    asked, hops = url, 0
    while True:
        dec = check(url, positions_dir=positions_dir, ledger_dir=ledger_dir)
        (pacer or _PACER).wait(dec.host, dec.floor)
        # a hold is written for a real fetch, or where the caller named its own ledger (a test's tmp folder): an
        # injected fetch with no ledger never holds a real host in the live file
        persist = fetch is None or ledger_dir is not None
        try:
            got = fetch(url, timeout) if fetch is not None else _go(url, timeout, headers, max_bytes)
        except (OSError, http.client.HTTPException) as exc:
            _strike(dec.host, f"{type(exc).__name__}: {str(exc)[:160]}", ledger_dir, persist)
            raise
        status, body, final = got[:3]
        if status in HOLD_STATUSES and persist:
            hold(dec.host, f"HTTP {status} on {url[:200]}", ledger_dir=ledger_dir)
        elif status in CHALLENGE_STATUSES:
            _strike(dec.host, f"HTTP {status}", ledger_dir, persist)
        else:
            _answered(dec.host)
        hdrs = got[3] if len(got) > 3 else {}
        loc = next((v for k, v in hdrs.items() if k.lower() == "location"), "") if status in REDIRECT_STATUSES else ""
        loc = urllib.parse.urljoin(url, loc) if loc else ""
        same_host = bool(loc) and host_of(loc) == host_of(asked)
        if loc and (hops < follow or (same_host and hops < same_host_hops)):
            url, hops = loc, hops + 1
            continue
        if status == 304:
            body = b""
        blocked = looks_challenged(status, body, hdrs)
        if blocked and status not in CHALLENGE_STATUSES and persist:
            hold(dec.host, f"{blocked[:200]} on {url[:200]}", ledger_dir=ledger_dir)
        return Fetched(asked, status, body, final, blocked, loc, dict(hdrs))


def pace(url_or_host: str, pacer: Pacer = None) -> float:
    """Block until the host's floor has passed, for a lane that does its own
    HTTP but must not set its own speed."""
    host = host_of(url_or_host) or url_or_host.lower()
    return (pacer or _PACER).wait(host, floor_for(host, _ROBOTS.get(host)))


def main(argv=None) -> int:
    """python -m support.fetchgate held | clear HOST --by NAME [--why TEXT]"""
    import argparse
    ap = argparse.ArgumentParser(prog="python -m support.fetchgate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("held")
    c = sub.add_parser("clear")
    c.add_argument("host")
    c.add_argument("--by", required=True)
    c.add_argument("--why", default="cleared")
    a = ap.parse_args(argv)
    if a.cmd == "held":
        for host, row in sorted(refusals().items()):
            print(f"{host}\theld since {row['at']}: {row['why']}")
        return 0
    if refused_by(a.host) is None:
        print(f"{a.host} is not held")
        return 1
    clear(a.host, a.by, a.why)
    print(f"{a.host} cleared by {a.by}")
    return 0

