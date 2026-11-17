"""The scraper registry — categories, readiness, and the activation policy.

Two categories (decision 2026-07-12):
  * "news"  — the ported outlets. Each runs individually every sweep: run.py runs
    the `runnable` ones and SKIPs blocked:credentials/antibot until unblocked
    (audit #30, 2026-08-30: NOT the old "none turn on until all ready" gate — the
    timer runs the ready ones now). "all-or-nothing" survives only as the
    EXIT-CODE policy — a hard-failing NEWS source reddens the unit, while
    "other"-category sources fail soft. Blocked sources are wired here so the
    only remaining work on them is unblocking.
  * "other" — dedicated-process sources (gazette, fyi/OIA, parliament/hansard,
    nzlii/courts, comcom, fma, …). Those live OUTSIDE newsscrapers as their own
    pipelines and are activated ONE AT A TIME as a consumer process needs their
    content. Gazette in particular is both ingested (backlog, parked from LLM
    news extraction per A0.4) AND consumed deterministically by
    data-layer/gazette_register to populate the entity graph — parking ≠ unused.

Status values: ready · blocked:credentials · blocked:antibot · blocked:robots ·
blocked:paywall · blocked:ruling. The runner attempts credential-blocked sources only when their
env vars are present, and skips antibot ones until the browser-fetch step
reading. `blocked:ruling` is a stop by Arthur's word that no credential, browser
or robots read can lift. Ruling 12 (QueryNZV4 plan, hard limit 8) took every
NZME masthead out of capture; it is WITHDRAWN as of ruling 169 (Arthur,
2026-11-11): the NZ Herald network (nzherald.co.nz and the sections it serves)
is collected again from 2026-10-18 01:15 NZ (when the old estate's scrapers
stopped) and BusinessDesk (NZME-owned) from 2026-10-17 10:50 NZ. Capture-
and-hold (ruling 115) still applies to the nzherald.co.nz network: raw bytes
land and are served raw, never extracted or embedded until an NZME licence
lands. The other NZME properties (newstalkzb, gisborneherald, oneroof,
driven) have no scraper and stay on the held list in
ingestion/news/review_sources.py. fyi.org.nz is out entirely (estate ruling
168) and is refused by ingestion/fetchgate.py (ruling 321). nbr.co.nz and
newsroom.co.nz stay blocked:credentials and are not fetched.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    module: str                # module name in this package
    category: str              # "news" (all-or-nothing) — "other" lives outside
    status: str                # ready | blocked:credentials | blocked:antibot | blocked:robots | blocked:paywall | blocked:ruling
    creds_env: tuple[str, ...] = ()   # env vars that unblock a credentials source


REGISTRY: dict[str, Entry] = {
    "stuff.co.nz":        Entry("stuffconz", "news", "ready"),
    # Stuff-family login (Arthur, 2026-11-13): VERIFIED sign-in via
    # identity.stuff.co.nz (Azure B2C form: Email address + Password); session
    # persisted /opt/data/evs-credentials/stuff_state.json. WEDDED TO THE
    # FETCH PATH 2026-11-17 (Arthur: "adopt logins for everything") —
    # every story-API fetch carries the subscriber session (provenance;
    # bodies measured identical anon vs logged-in, 15/15 The Press). Mint or
    # refresh per-host states with ingestion/scripts/stuff_login.py.
    # The Press (Christchurch, Stuff masthead) — added 2026-11-13 on Arthur's
    # word ("Do it"), OUTSIDE the estate's 87-source media list; told to the
    # estate under hermes-thepress@2026-11-13. Stuff masthead SPA + open story
    # API; completeness MEASURED (anon bodies = logged-in bodies, 15/15).
    # On-site archive back to 2023-12-13 (ARCHIVE walk joins the media
    # schedule). Platform facts + suite map: newsscrapers/stuffmasthead.py.
    "thepress.co.nz":     Entry("thepress", "news", "ready"),
    # The Post (Wellington) + Waikato Times — the rest of the Stuff masthead
    # suite (2026-11-13 "full suite" ruling): thepost carries the Taranaki
    # Daily News, Manawatu Standard and Sunday Star-Times sections; every
    # regional title 301s into a section of these hosts (map in
    # stuffmasthead.py) so the three hosts' sitemaps cover the whole suite.
    "thepost.co.nz":      Entry("thepost", "news", "ready"),
    "waikatotimes.co.nz": Entry("waikatotimes", "news", "ready"),
    "scoop.co.nz":        Entry("scoop", "news", "ready"),
    # ODT paywalled 2026-11-09 (measured: subscriber teaser only, body absent
    # from the HTML and the SSR payload). LIFTED 2026-11-11 by the subscriber
    # lane: the body is served complete to any plain HTTP fetch carrying the
    # logged-in Piano cookies (measured 48-char teaser anon vs 3,881 chars
    # with the jar); the jar is minted by a one-time browser login through
    # the Piano identity iframe (reCAPTCHA anchored but never challenges) and
    # persisted to odt_state.json (__utp JWT, ~1yr). fetch_all is plain httpx
    # over the jar + one re-login per run only if the teaser reappears.
    # creds_env gates the run (and the re-login) like businessdesk.
    "odt.co.nz":          Entry("odtconz", "news", "blocked:credentials",
                                ("ODT_EMAIL", "ODT_PASSWORD")),
    "rnz.co.nz":          Entry("rnzscraper", "news", "ready"),
    "thespinoff.co.nz":   Entry("spinoff", "news", "ready"),
    "kiwiblog.co.nz":     Entry("kiwiblog", "news", "ready"),
    # Allied Media standalone regionals (2026-07-16 ecosystem audit — the other
    # mastheads redirect into odt.co.nz sections and ride the ODT sitemap walk)
    # STOPPED 2026-09-18 by the first weekly robots read (ruling 288): its
    # robots.txt cannot be read at all any more and the host no longer allows
    # our user-agent. Permission unknown is a REFUSAL (ruling 78), so the lane
    # does not run — it is not "failing", it is not permitted. This also
    # explains the 18-sweep failure streak queue 10 parked on 2026-09-18: the
    # site had already closed to us. Revive it only if a later Monday read
    # shows robots readable and allowing us again.
    "greystar.co.nz":     Entry("greystar", "news", "blocked:robots"),
    # ashburtoncourier.co.nz RETIRED 2026-08-14: the whole site (wp-json
    # included) now 301s into odt.co.nz/canterbury/mid-canterbury — Allied
    # folded it like the other mastheads above; coverage rides the ODT walk.
    # business/finance — high entity density (source-expansion §9, 2026-07-16)
    "interest.co.nz":     Entry("interestconz", "news", "ready"),
    # more free sources — generic RSS scraper (§9 batch, 2026-07-17)
    "guardianonline.co.nz":      Entry("guardianonline", "news", "ready"),
    "sciencemediacentre.co.nz":  Entry("sciencemediacentre", "news", "ready"),
    # Rural News Group refuses every route 2026-11-09 (measured): 403 direct
    # (plain + browser UA), 403 via the residential proxy, and the headless
    # browser is CHALLENGED on the feed as well. Nothing further to try — a
    # challenged read is a failed read, and the stop IS the remedy (ruling 290).
    "ruralnewsgroup.co.nz":      Entry("ruralnews", "news", "blocked:antibot"),
    # §9 batch 2 (2026-07-17) — generic RSS + Arc/Fusion
    "thestandard.nz":            Entry("thestandard", "news", "ready"),
    # thedailyblog 302-redirects non-browser UAs to http://127.0.0.1 (WP
    # security-plugin trap) and its feed carries excerpts only, not full body —
    # deferred pending a browser fetch. Module kept, marked antibot.
    "thedailyblog.co.nz":        Entry("thedailyblog", "news", "blocked:antibot"),
    # e-tangata regressed 2026-07-17: its /feed/ now returns a Sucuri
    # `sgcaptcha` challenge (HTTP 202 → /.well-known/sgcaptcha/). Worked in
    # batch 2; now CAPTCHA-gated, which we don't bypass. Module kept.
    "e-tangata.co.nz":           Entry("etangata", "news", "blocked:antibot"),
    "farmersweekly.co.nz":       Entry("farmersweekly", "news", "ready"),
    "teaonews.co.nz":            Entry("teaonews", "news", "ready"),
    "1news.co.nz":               Entry("onenews", "news", "ready"),
    # NZME / NZ Herald network (14 mastheads via one Arc feed). CAPTURE-AND-HOLD
    # (ruling 115): robots permits our UA, but the terms bar ML/AI/commercial
    # use, so base.run_source lands every nzherald.co.nz URL as pipeline_status
    # 'held' (review_sources.HELD_SOURCE_DOMAINS) — captured, never extracted
    # or embedded until an NZME licence lands. Ready to scrape; held by policy.
    # Ruling 12 (2026-10-18: NZME out by name) is WITHDRAWN — ruling 169
    # (Arthur, 2026-11-11, answering the QueryNZ estate's provider ask):
    # collect the NZME mastheads from 2026-10-18 01:15 NZ, when the old
    # estate's scrapers stopped. Capture-and-hold (ruling 115) stands.
    # PREMIUM collected since 2026-11-13: measured 20/20 premium URLs serving
    # FULL bodies to plain anon fetches (550-14,842 chars); Arthur's word
    # behind the robots route (creds handed over 2026-11-13 = proceed
    # politely). The login is PARKED: nzme.env creds rejected by the identity
    # service (one attempt, held per house rule) — nothing needs them while
    # bodies are served as they are.
    "nzherald.co.nz":            Entry("nzme", "news", "ready"),
    # §9 batch 3 (2026-07-17) — sitemap + HTML discovery (no RSS)
    "crux.org.nz":               Entry("crux", "news", "ready"),
    "sunlive.co.nz":             Entry("sunlive", "news", "ready"),
    # §9 batch 5 (2026-07-17) — community/sector sweep. stoppress + times.co.nz
    # fetch articles through the headless browser (Cloudflare TLS-fingerprint
    # 403s curl-class clients; the RSS discovery still works plain).
    "waateanews.com":            Entry("waatea", "news", "ready"),
    "kanivatonga.co.nz":         Entry("kanivatonga", "news", "ready"),
    # STOPPED 2026-10-08 (C215). Measured, reproducibly: the FIRST page of a
    # browser batch renders fully (258 KB, 3,834 chars of article) and EVERY
    # page after it comes back as Cloudflare's "Just a moment..." interstitial —
    # 29,045 bytes, no content. A challenged read is a failed read, so this host
    # is refusing us past one page per context and the lane must stop asking
    # (ruling 290: the stop is the whole remedy). It had been invisible because
    # the challenge shell exceeded `render_all`'s `len > 20_000` escape and only
    # Incapsula's marker was checked, so 19 of 20 pages were counted THIN — the
    # publisher's fault, not the refusal it was. robots PERMITS us (read
    # 2026-10-05): this is the WAF, not the permission surface, and nothing here
    # is to be worked around. times.co.nz is NOT affected — its archive pages
    # render fully, four of four, and it stays ready.
    "stoppress.co.nz":           Entry("stoppress", "news", "blocked:antibot"),
    "localmatters.co.nz":        Entry("localmatters", "news", "ready"),
    "times.co.nz":               Entry("timesonline", "news", "ready"),
    "baybuzz.co.nz":             Entry("baybuzz", "news", "ready"),
    "greaterauckland.org.nz":    Entry("greaterauckland", "news", "ready"),
    # ourauckland went behind a site-wide bot wall 2026-07-26 (403 on the RSS
    # AND the homepage, browser UA included) — its hard-fail was aborting the
    # whole daily unit (news is all-or-nothing). Candidate for the headless-
    # browser fetch (Incapsula precedent) if the wall persists.
    "ourauckland.aucklandcouncil.govt.nz": Entry("ourauckland", "news", "blocked:antibot"),
    # voxy.co.nz serves a 10KB JS shell for every URL (article body only renders
    # client-side) — a press-release aggregator isn't worth browser cycles;
    # module kept, blocked until/unless that changes.
    "voxy.co.nz":                Entry("voxy", "news", "blocked:antibot"),
    # §9 batch 6 (2026-07-17) — Pasifika/regional/student/trade sweep.
    # NB starnews.co.nz (Christchurch Star) redirects into odt.co.nz/star-news
    # and already rides the ODT sitemap walk (876 articles held) — no module.
    "tpplus.co.nz":              Entry("tagatapasifika", "news", "ready"),
    "valleyprofile.co.nz":       Entry("valleyprofile", "news", "ready"),
    "critic.co.nz":              Entry("critic", "news", "ready"),
    "wbn.co.nz":                 Entry("wbn", "news", "ready"),
    "thelawyermag.com":          Entry("nzlawyer", "news", "ready"),
    "insurancebusinessmag.com":  Entry("insurancebiz", "news", "ready"),
    # §9 batch 7 (2026-07-17) — official releases (Crown content, open robots).
    # Police names accused persons: capture rides the normal news path (like
    # beehive); person-link DISPLAY is governed by the compliance gates.
    "police.govt.nz":            Entry("police", "news", "ready"),
    "worksafe.govt.nz":          Entry("worksafe", "news", "ready"),
    # C200 (2026-10-06), dry-verified on the real surface: the FEED is healthy
    # (50 items) but every article page renders a 32 KB SHELL — no og:title, the
    # h1 is the site banner, four <p> elements, longest 152 chars — so the
    # extractor returns None and the lane lands NOTHING. The browser fetch was
    # already the workaround for this host's WAF ("403 curl-class TLS, same
    # class as stoppress"); that workaround is now defeated too, which is the
    # same anti-bot class escalated, and the sibling entry
    # `rbnz.govt.nz/enforcement` has carried `blocked:antibot` since B1/S1.
    # Marked so the daily sweep stops reporting success on a lane that cannot
    # land a document — a lane that runs and lands nothing is worse than one
    # that refuses, because only the second is visible.
    "rbnz.govt.nz":              Entry("rbnz", "news", "blocked:antibot"),
    # batch 7b — feedless agencies via HTML discovery (2026-07-17)
    "mpi.govt.nz":               Entry("mpi", "news", "ready"),
    "ird.govt.nz":               Entry("ird", "news", "ready"),
    "sfo.govt.nz":               Entry("sfo", "news", "ready"),
    "linz.govt.nz":              Entry("linz", "news", "ready"),
    # councils sweep (2026-07-17): of 16 probed, ONLY ECan exposes a feed —
    # the rest (incl. Newsline ChCh, Wellington CC) serve bot-wall stubs.
    "ecan.govt.nz":              Entry("ecan", "news", "ready"),
    # trade-press wave tier 1 (2026-07-25) — sector wires for the topical
    # watchlists/Papers (todo §source-expansion). woodweek.com 301s into
    # fridayoffcuts.com (one scraper covers both forestry weeklies);
    # tourismticker.com is hard-paywalled per-article (NBR class — module
    # only worth building if a subscription is taken).
    "seafood.co.nz":             Entry("seafoodnz", "news", "ready"),
    "fridayoffcuts.com":         Entry("fridayoffcuts", "news", "ready"),
    "buildingtoday.co.nz":       Entry("buildingtoday", "news", "ready"),
    "constructionnews.co.nz":    Entry("constructionnews", "news", "ready"),
    "hospitalitybusiness.co.nz": Entry("hospitalitybusiness", "news", "ready"),
    # research-sector wave (2026-07-25): think tanks + public research.
    # Assessed, not built: Treasury pubs (PDF-heavy → DocSource lane),
    # phfscience.nz/ESR (item selectors unverified), Scion/AgResearch/
    # Landcare/GNS (dead or Imperva-walled post CRI-merger; the choke point
    # is bot-shielded bioeconomyscience.co.nz), university OAI-PMH repos
    # (5 endpoints verified live — a metadata pipeline, not a news scraper;
    # design queued in todo).
    "nzier.org.nz":              Entry("nzier", "news", "ready"),
    # WAF 403s self-identified bots while robots.txt allows everything;
    # module declares a browser USER_AGENT (Arthur 2026-08-14: "wear the
    # disguise") — see infrastructurenz.py docstring for the test record.
    "infrastructure.org.nz":     Entry("infrastructurenz", "news", "ready"),
    "niwa.co.nz":                Entry("niwa", "news", "ready"),
    "maxim.org.nz":              Entry("maxim", "news", "ready"),
    "phcc.org.nz":               Entry("phcc", "news", "ready"),
    "royalsociety.org.nz":       Entry("royalsociety", "news", "ready"),
    "nzinitiative.org.nz":       Entry("nzinitiative", "news", "ready"),
    "berl.co.nz":                Entry("berl", "news", "ready"),
    "motu.nz":                   Entry("motu", "news", "ready"),
    "helenclark.foundation":     Entry("helenclark", "news", "ready"),
    # trade-press wave tier 2 (2026-07-25). Assessed, not built: OneRoof
    # (NZME blocked class — robots allow /news but the publisher class is
    # excluded); nzlogger.co.nz + nztruckanddriver.co.nz (shared custom CMS,
    # monthly magazine features, mostly machinery reviews — marginal graph
    # value while Friday Offcuts covers forestry weekly; revisit if thin);
    # LockerRoom (ZERO WORK — Newsroom's public RSS carries all sections, so
    # it rides the newsroom module whenever its credentials unblock).
    "energyresources.org.nz":    Entry("energyresources", "news", "ready"),
    "nzpam.govt.nz":             Entry("nzpam", "news", "ready"),
    "nztrucking.co.nz":          Entry("nztrucking", "news", "ready"),
    "newsroom.co.nz":     Entry("newsroom", "news", "blocked:credentials",
                                ("NEWSROOM_EMAIL", "NEWSROOM_PASSWORD")),
    "nbr.co.nz":          Entry("nbr", "news", "blocked:credentials",
                                ("NBR_ACCOUNT_EMAIL", "NBR_ACCOUNT_PASSWORD")),
    # NZME-owned. Ruling 12 withdrawn — ruling 169 (Arthur, 2026-11-11):
    # collect from 2026-10-17 10:50 NZ, when the old estate's scrapers
    # stopped. Discovery rebuilt onto the Arc sitemaps (the monthly
    # articles-sitemap-YYYYMM is gone; 2026-11-11). The LOGIN LANE WORKS
    # (verified 2026-11-11 with Arthur's own BusinessDesk account; the Arc
    # identity flow is in businessdesk._perform_sign_in): runs when the
    # creds are present, like newsroom/nbr. Unauthenticated it serves
    # subscriber teasers only (395 discovered / 100 fetched / 100 thin /
    # 0 landed, measured 2026-11-11).
    "businessdesk.co.nz": Entry("businessdesk", "news", "blocked:credentials",
                                ("BUSINESSDESK_EMAIL", "BUSINESSDESK_PASSWORD")),
    # anti-bot (Incapsula) cleared via headless-browser fetch (2026-07-16)
    # beehive.govt.nz PARKED:EXTERNAL (Arthur, 2026-11-09): beehive-scraper is
    # the holder AND the runner (its own crons + IPRoyal/chromium); the MCP
    # beehive corpus holds 70,967 URLs. This module must not sweep the host —
    # and the holdings gate would drop every URL anyway. Also parked on the
    # list and NEVER to be added to this registry: zz-cron (not in this tree —
    # Arthur has a cron for it already, 2026-11-09).
    "beehive.govt.nz":    Entry("beehive", "news", "parked:external"),
    # Next.js SPA — headless-browser discovery + fetch (2026-07-17). No
    # robots.txt (falls through to the app shell), so nothing is disallowed.
    "pmn.co.nz":          Entry("pmn", "news", "ready"),

    # ── decision corpora (htmlsource class, 2026-07-26) — official bodies
    # publishing decisions/case notes as HTML pages. Category "other": they
    # activate independently and their failures never abort the news sweep.
    "privacy.org.nz":     Entry("privacycasenotes", "other", "ready"),
    "linz.govt.nz/oio":   Entry("oiodecisions", "other", "ready"),   # was "linz.govt.nz" — collided with the linz news scraper (B1/S1 2026-08-28)
    # tier-3 recon wave (2026-07-26): official emissions, category "other"
    "police.govt.nz/archive": Entry("policenews", "other", "ready"),   # was "police.govt.nz" — collided with the police news scraper (B1/S1 2026-08-28)
    "insolvency.govt.nz": Entry("insolvencynotices", "other", "ready"),
    "hrc.govt.nz":        Entry("hrcrepository", "other", "ready"),
    "royalsociety.org.nz/marsden": Entry("marsdenawards", "other", "ready"),
    # RBNZ Cloudflare UA-filters non-browser clients (403 on sitemap.xml with
    # our honest UA, 2026-07-26) — browser-fetch tier, like beehive
    "rbnz.govt.nz/enforcement": Entry("rbnznews", "other", "blocked:antibot"),   # was "rbnz.govt.nz" — collided with the rbnz news scraper (B1/S1 2026-08-28)
    "sfo.govt.nz/cases":  Entry("sfonews", "other", "ready"),   # was "sfo.govt.nz" — collided with the sfo news scraper (B1/S1 2026-08-28)
    "medsafe.govt.nz":    Entry("medsaferecalls", "other", "ready"),
}


def runnable(name: str) -> tuple[bool, str]:
    """Can this source actually run right now? (blocked reasons resolve
    dynamically: credentials present → runnable.)"""
    e = REGISTRY[name]
    if e.status == "ready":
        return True, "ready"
    if e.status == "blocked:credentials":
        missing = [v for v in e.creds_env if not os.environ.get(v)]
        return (not missing,
                "ready (credentials present)" if not missing
                else f"blocked: missing {', '.join(missing)}")
    if e.status == "blocked:ruling":
        return False, ("blocked: ruled out by name (ruling 12, QueryNZV4 hard limit 8: "
                       "NZME is not captured, indexed or read). Nothing lifts this")
    if e.status == "blocked:robots":
        # NOT a fault to fix: the host withdrew permission, or its robots.txt
        # can no longer be read, and permission unknown is a refusal (ruling
        # 78). Only a later weekly read (ruling 288) may put it back to ready.
        return False, "blocked: robots.txt refuses us or cannot be read (ruling 78; weekly read, ruling 288)"
    if e.status == "blocked:paywall":
        return False, ("blocked: paywall — the host serves subscriber teasers, "
                       "not the article. A subscription + login lane lifts it; "
                       "until then the lane cannot land and stays visibly stopped")
    # C215 (2026-10-08): this used to read "needs browser fetch", which is the
    # right remedy for a source that has no browser lane and the WRONG one for a
    # source that has one and is challenged anyway — it sends the next reader to
    # do the thing that already failed. stoppress.co.nz has rendered through the
    # headless browser since 2026-07-17 and every page after the first comes back
    # as Cloudflare's interstitial.
    return False, ("blocked: anti-bot — the host serves a challenge instead of "
                   "the page. A browser lane is the ruled exception where robots "
                   "PERMITS and the WAF blocks a plain UA (SCRAPING_RULES §1); "
                   "where the browser is challenged too there is nothing further "
                   "to try, a challenged read is a failed read, and the stop IS "
                   "the remedy (ruling 290)")
