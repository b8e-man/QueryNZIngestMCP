# Where grants are published: the survey of 21 October 2026 (grants-1)

Through the fetch gate, daytime, serial, 5 s apart (the catalogue's 10 s honoured): 105 page requests and one
robots file per host. Each society: its home page, then at most three of its own pages whose link says grants.

## The Department of Internal Affairs (read)

| What | Where | Shape | Window | Licence |
| --- | --- | --- | --- | --- |
| National file of class 4 grants, "Grants from Gaming Machine Profits" | catalogue.data.govt.nz, package `class-4-grants-data` | one CSV, 178,739 records, 19 columns: society, recipient as reported, final name, NZBN, charity number, status (Accepted 116,684, Declined 62,047, Refunded 8), amounts requested and granted, decision date, year, two categories, refund, territorial authority, region. No purpose | decisions 2021 to 2025; updated yearly | CC BY 4.0 |
| Lottery committees' records of grants | www.communitymatters.govt.nz, one page per committee and round | an h1 and one table, Name and Amount, an asterisk for a multi-year grant. No purpose, no date, no number | the financial year in the heading | Crown copyright; the Department's CC BY 4.0 (its own page not read) |
| The list of operating societies | granted.govt.nz (script bundle) | 31 societies, 770 venues, each society's website | 21 October 2026 | the Department's |

The Lottery records hang off no index page. The site's "ask us" answer that lists them refused (HTTP 403), so
the capture walks the site whole. The old Lottery recipient CSVs on the catalogue (to 2017/18) were not
reached: the catalogue then served a challenge.

## The 31 societies (surveyed, not read)

| Class | Societies | What the survey saw |
| --- | --- | --- |
| A. Grants lists as files | NZ Community Trust (one PDF, 2023/24 to July 2026); Air Rescue Services (approved and declined, quarterly, 2017 to 2025, about 40 PDFs, typed: exported from Excel); Pelorus Trust (approved and declined pages, 24 PDFs, 2025 to 2026); Aotearoa Gaming Trust (funding distributions, 3 PDFs); One Foundation (9 PDFs, 2020 seen); Trust Aoraki (a table of monthly PDFs, 2013 to 2026, 37); New Horizon (approved grants, 2 PDFs); Milestone Foundation (41 PDFs, 2020 to 2024); We Care (historical grants, 22 PDFs, 2021 to 2026) | Each society its own layout: one profile per layout, read from the text layer |
| B. Grants pages reached, no list among the first three | Pub Charity, Lion Foundation, Mainland, Bluesky, ILT (one spreadsheet, a form), Dragon, Grassroots Central, Rano, Kiwi Gaming, First Light (its menu names "Applications approved" and "declined", not reached), Oxford Sports Trust, Akarana | The whole-site walk from the grants page will find the list or show there is none |
| C. No grants link on the home page | Grassroots Trust, North and South Trust, The Trusts Community Foundation, Trust House, Redwood, Constellation | Likely built by script or a portal; a walk, then a headed browser shown no challenge |
| D. The listed address is dead | Four Winds Foundation and Manukau Counties Community Facilities (both `fourwindsfoundation.co.nz/MCCFCT`, 404) | The Department's list carries a broken address |
| E. Grants on another host | Trillian (`trillian.co.nz`, now named in the position), Youthtown (`youthtowntrust.org.nz`, not named) | The gate refused, correctly |

Every society's 2021 to 2025 grants are already in the Department's file. The societies' own lists add 2017 to
2020 (ruling 71's window) and the purpose as printed.

## Class A read (grants-2, 22 October 2026)

The walk from each grants page (one link deep; two for One Foundation; the job walks two), at night, serial, 5 s apart: 321 requests (the gate's ledger), 235 files landed (no
block, no challenge). 100 read under eleven profiles (15,524 decisions), 114 carded by hash in `unprofiled.list`,
14 not lists (refunds, forms, policies), 7 scans.

| Society | Read | Carded |
| --- | --- | --- |
| Air Rescue | every quarter July 2017 to June 2026 but one; 2021 to 2025 agree with the national file within 0.12% (count) and 0.02% (money) | April to June 2020 (pictures) |
| Pelorus | every meeting December 2025 to June 2026, approved and declined; printed totals agree | the 28 April 2026 declined list is not published: its link serves the approved list |
| Aotearoa Gaming Trust | 2026 quarters 1 to 3 | earlier years not linked |
| Trust Aoraki | August, October, December 2025 (purpose printed) | A3 sheets 2016 to 2022 (blocks side by side), 2024 to 2025 posters, 4 scans |
| Milestone | every month November 2017 to March 2020 | 2020 to 2026 in several layouts, purpose printed |
| New Horizon | June 2024 to May 2026, approved and unsuccessful | |
| We Care | 2022 quarters (52 grants against the national file's 55) | declined lists, 2023 to 2025 annual reports |
| NZ Community Trust | | its one list redirects to `static1.squarespace.com`, a host no position names |
| One Foundation | | its lists are built by script: no list in the page |

## Regional development and tertiary funding (grants-2, 22 October 2026; ruling 61)

Seven page requests through the gate under the draft position `position/regional-development-and-tertiary-funding.md`.

| Publisher | What | Shape | Terms | Outcome |
| --- | --- | --- | --- | --- |
| Kānoa, MBIE's regional development unit (growregions.govt.nz) | "All Kānoa managed projects" (Provincial Growth Fund, Regional Strategic Partnership Fund, Regional Infrastructure Fund and others), as of August 2026 | one xlsx; a PDF overview of the funds | CC BY-NC 4.0 (its copyright page): no commercial use without permission | **not landed**; carded, queue |
| Tertiary Education Commission (tec.govt.nz) | funding allocations per provider (Education Counts points there) | not seen | not read | **challenged** (Incapsula) on the first request: a failed read; carded |
| Ministry of Education, Education Counts | the financial resourcing of tertiary education | aggregate tables, no recipient-level grants seen | CC BY 4.0 | nothing to read for this lane |
