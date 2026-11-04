# Where councils publish their candidates' returns: the survey of 22 October 2026 (local-elections-1)

Through the fetch gate, daytime, one request at a time, at least 5 s apart (each robots file's crawl delay
honoured: 7 s for most councils, 30 s for Ōtorohanga): 410 requests (the gate's ledger), the robots files with
them, then 110 for the first listings pass (89 pages: 21 asked twice, where two seeds of one council linked the
same page; fixed, each page once a pass). Nothing blocked the listings pass. No model.

## One collected source? No

| Place | What it holds | Outcome |
| --- | --- | --- |
| electionz.com (an electoral officer contractor) | a "Local Government Election Returns" page per council, 2010 and 2013 only (`545b6e88…`) | outside the window; nothing for 2019 onward |
| electionservices.co.nz (the other contractor) | iwi, trust and board elections | no council returns |
| lgnz.co.nz, votelocal.co.nz | guidance for candidates and voters | no returns |
| The Department of Internal Affairs | no local election returns are collected by any department | none |

So the lane goes council by council (s 112F puts the duty on each council's electoral officer). The councils'
pages were found by a web search for addresses only (no page read that way), then every page and every terms
page asked through the gate. A blind sitemap walk was tried first and stopped: four hosts took 60 requests and
found nothing a search did not.

## The 78 councils

Returns listed counts what the listing reader found on the pages at the survey (in window; one combined file
counts once). The capture's own counts, per page and file, are in the capture tables.

| Council | In-window returns listed at the survey | Terms read (sha256) | Outcome |
| --- | --- | --- | --- |
| Northland Regional Council | 2019: 19, 2022: 24, 2025: 21 | personal or non-commercial use `0c664288…` | seeded |
| Waikato Regional Council | - | none found | failed read: challenge |
| Bay of Plenty Regional Council | 2017: 1 | personal or non-commercial use `11a9ea05…` | seeded |
| Hawke's Bay Regional Council | 2019: 2, 2022: 27, 2025: 41 | personal or non-commercial use `4f562426…` | seeded |
| Taranaki Regional Council | 2025: 3 | a copyright line, no licence `45b971ac…` | seeded |
| Horizons Regional Council | 2019: 2, 2022: 2, 2025: 1 | a copyright line, no licence `fa3f879a…` | seeded |
| Greater Wellington Regional Council | 2025: 31 | CC BY `da864ef1…` | seeded |
| Environment Canterbury | - | none found | failed read: challenge |
| West Coast Regional Council | 2022: 19, 2025: 16 | privacy page only `159b1bbf…` | seeded |
| Otago Regional Council | 2022: 24, 2025: 22 | CC BY `6513a145…` | seeded |
| Environment Southland | - | personal or non-commercial use `ab5e97cb…` | no listing found (card) |
| Auckland Council | - | bars automated access `e58a2ac9…` | held on its terms (queue) |
| Gisborne District Council | 2022: 40 | personal or non-commercial use `1e9eed28…` | seeded |
| Tasman District Council | - | personal or non-commercial use `c63dc4a3…` | folder addresses unencoded (fixed); re-asked in the next survey |
| Nelson City Council | 2019: 2, 2022: 2 | a copyright line, no licence `20b67d2a…` | seeded |
| Marlborough District Council | 2022: 24 | privacy page only `426888a0…` | seeded |
| Chatham Islands Council | - | none found | failed read: challenge |
| Far North District Council | 2022: 1, 2025: 1 | a copyright line, no licence `c54e489a…` | seeded |
| Whangārei District Council | - | personal or non-commercial use `374aa52a…` | no listing found (card) |
| Kaipara District Council | 2022: 29 | a copyright line, no licence `6793972f…` | seeded |
| Hauraki District Council | - | a copyright line, no licence `e1031924…` | no listing found (card) |
| Thames-Coromandel District Council | 2022: 52, 2025: 65 | a copyright line, no licence `c5aa233e…` | seeded |
| Waikato District Council | - | personal or non-commercial use `ea76a65a…` | no listing found (card) |
| Hamilton City Council | 2019: 45, 2022: 47, 2024: 15, 2025: 59 | personal or non-commercial use `c25f0603…` | seeded |
| Waipā District Council | 2019: 32, 2022: 43, 2023: 4 | personal or non-commercial use `e8bd34d1…` | seeded |
| Matamata-Piako District Council | - | none found | failed read: challenge |
| Ōtorohanga District Council | 2019: 26, 2020: 3, 2021: 1, 2022: 22, 2025: 23 | personal or non-commercial use `42ecfa60…` | seeded |
| South Waikato District Council | 2019: 39, 2022: 5, 2025: 5 | bars automated access `ae3f55ce…` | held on its terms (queue) |
| Taupō District Council | 2019: 30 | personal or non-commercial use `36f6e9a2…` | seeded |
| Waitomo District Council | 2022: 2, 2025: 2 | a copyright line, no licence `7d8379a9…` | seeded |
| Rotorua Lakes Council | 2019: 51, 2022: 38 | a copyright line, no licence `30346139…` | seeded |
| Tauranga City Council | 2024: 142 | personal or non-commercial use `73d3119a…` | seeded |
| Western Bay of Plenty District Council | - | a copyright line, no licence `f1334106…` | no listing found (card) |
| Whakatāne District Council | 2022: 59, 2025: 44 | personal or non-commercial use `6153e4b5…` | seeded |
| Kawerau District Council | 2022: 1, 2025: 41 | personal or non-commercial use `7d924590…` | seeded |
| Ōpōtiki District Council | - | privacy page only `18e49c78…` | no listing found (card) |
| Wairoa District Council | 2019: 4, 2022: 4, 2025: 3 | reuse on request or permission `828cef2d…` | seeded |
| Hastings District Council | 2017: 12, 2019: 1, 2022: 1, 2025: 1, 2026: 1 | reuse on request or permission `f0ebe920…` | seeded |
| Napier City Council | 2019: 24, 2022: 22, 2025: 23 | reuse on request or permission `f915ef18…` | seeded |
| Central Hawke's Bay District Council | 2019: 11, 2020: 3, 2022: 10 | reuse on request or permission `6a5b75f3…` | seeded |
| New Plymouth District Council | 2022: 78, 2025: 86 | personal or non-commercial use `3dfba6fd…` | seeded |
| Stratford District Council | - | personal or non-commercial use `b877384b…` | no listing found (card) |
| South Taranaki District Council | - | none found | no listing found (card) |
| Ruapehu District Council | - | a copyright line, no licence `5ad4cc27…` | no listing found (card) |
| Whanganui District Council | 2019: 10, 2025: 1 | personal or non-commercial use `96fadc15…` | seeded |
| Rangitīkei District Council | 2022: 8, 2024: 3, 2025: 8 | a copyright line, no licence `b46d19f3…` | seeded |
| Manawatū District Council | 2025: 1 | personal or non-commercial use `6b19e454…` | seeded |
| Palmerston North City Council | 2019: 60, 2021: 20, 2025: 88 | CC BY `d6c3d5d2…` | seeded |
| Tararua District Council | - | personal or non-commercial use `80aed9ee…` | no listing found (card) |
| Horowhenua District Council | 2022: 58 | personal or non-commercial use `a8cfb32d…` | seeded |
| Kāpiti Coast District Council | 2019: 3, 2026: 85 | personal or non-commercial use `b68df5f7…` | seeded |
| Porirua City Council | - | reuse on request or permission `917fa4c5…` | no listing found (card) |
| Upper Hutt City Council | - | personal or non-commercial use `17f56d67…` | no listing found (card) |
| Hutt City Council | 2019: 73, 2022: 68, 2025: 45 | privacy page only `5d8d4eab…` | seeded |
| Wellington City Council | - | not read (403) | failed read: HTTP 403 |
| Masterton District Council | - | none found | no listing found (card) |
| Carterton District Council | - | not read (403) | failed read: HTTP 403 |
| South Wairarapa District Council | 2019: 30, 2022: 36, 2025: 37, 2026: 7 | a copyright line, no licence `308dc75f…` | seeded |
| Buller District Council | - | personal or non-commercial use `452b4ed7…` | no listing found (card) |
| Grey District Council | - | personal or non-commercial use `939a8606…` | no listing found (card) |
| Westland District Council | - | personal or non-commercial use `e48d5140…` | no listing found (card) |
| Kaikōura District Council | 2022: 15, 2025: 17 | a copyright line, no licence `b9265e0d…` | seeded |
| Hurunui District Council | - | none found | no listing found (card) |
| Waimakariri District Council | 2019: 4, 2022: 3, 2025: 1 | bars automated access `2d7bfc08…` | held on its terms (queue) |
| Christchurch City Council | 2025: 117 | bars automated access `b340b707…` | held on its terms (queue) |
| Selwyn District Council | 2025: 24 | reuse on request or permission `114f5d5d…` | seeded |
| Ashburton District Council | - | none found | no listing found (card) |
| Timaru District Council | - | personal or non-commercial use `503358ef…` | no listing found (card) |
| Mackenzie District Council | - | not read (403) | failed read: HTTP 403 |
| Waimate District Council | 2022: 16 | privacy page only `e38f13d8…` | seeded |
| Waitaki District Council | 2019: 18, 2022: 16, 2025: 16 | personal or non-commercial use `bb45624b…` | seeded |
| Central Otago District Council | - | none found | no listing found (card) |
| Queenstown-Lakes District Council | - | none found | failed read: a redirect to a bot manager challenge |
| Dunedin City Council | 2019: 9, 2025: 100 | reuse on request or permission `673bdefd…` | seeded |
| Clutha District Council | 2019: 1, 2020: 1, 2021: 1 | privacy page only `28a6755e…` | seeded |
| Southland District Council | - | a copyright line, no licence `5731a7ba…` | failed read: a CAPTCHA |
| Gore District Council | 2022: 41, 2023: 5, 2025: 36 | personal or non-commercial use `69ff7726…` | seeded |
| Invercargill City Council | - | a copyright line, no licence `c908da5c…` | no listing found (card) |

The seeded councils' pages are `listings.tsv`. Licensing trusts publish nothing themselves: their candidates'
returns are on the council of the district (Invercargill for the ILT, Gore for Mataura, Waitaki's trust on
Waitaki's page). "No listing found" means the addresses the search gave were dead (404) or held no returns:
those councils, Tasman's folders (now encoded) and the HTML-only returns (South Taranaki's and Clutha's totals
on the page, Whanganui's 2019 page per candidate) are carded for a second survey.
