"""Medsafe product recalls (medsafe.govt.nz) — the MORD database behind a
classic ASP form POST (recon 2026-07-26: no robots.txt → unrestricted; no JS
needed). Discovery POSTs the search form for the trailing 180 days and walks
RecallDetail.asp?ID= links; the ledger dedups re-sweeps. Full back-catalogue
(records since 2012) = widen the date window at cluster time."""
from __future__ import annotations

import re
from datetime import date, timedelta

from . import base, htmlsource

SOURCE = "medsafe.govt.nz"

_SEARCH = "https://www.medsafe.govt.nz/hot/Recalls/RecallSearch.asp"
_DETAIL = "https://www.medsafe.govt.nz/hot/Recalls/RecallDetail.asp?ID={}"


async def discover(client) -> list[base.FeedItem]:
    frm = (date.today() - timedelta(days=180)).strftime("%d %b %Y").lstrip("0")
    r = await client.post(_SEARCH + "#results", data={
        "optType": "All", "txtName": "", "Ingredients": "",
        "txtDateFrom": frm, "txtDateTo": "", "cmdSearch": "Search"})
    ids = list(dict.fromkeys(re.findall(r"RecallDetail\.asp\?ID=(\d+)", r.text)))
    return [base.FeedItem(url=_DETAIL.format(i)) for i in ids]


extract = htmlsource.make_extract(category="recall", selector="main, body")
