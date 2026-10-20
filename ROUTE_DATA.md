# Route data for the airline cases

All inputs, source PDFs and calculations are inside this case-study folder. The observation cutoff is July 2026.

## What is available

| Input in `data/routes/` | Contents | What it can measure |
|---|---|---|
| `domestic_route_monthly.csv` | 134,958 directed airport-pair/month passenger records, April 2015–July 2026; individual coverage varies | Actual route demand across all airlines. Airline identity is absent. |
| `top20_monthly_airline_shares.csv`, `top20_monthly_route_hhi.csv` | 1,114 airport-pair/month observations across 20 major routes and 64 covered months, April 2019–July 2026 | Airline scheduled-frequency shares and HHI on covered major routes. |
| `regional_schedule_rows.csv`, `regional_schedule_manifest.json` | Extracted movement rows from 34 original filings for summer/winter 2019 and winter 2021 | Extension to TruJet's own routes, including small regional markets. |
| `top20_source_rows.csv`, `top20_original_pdfs.json` | Source rows and 92 source-PDF references supporting the major-route panel | Traceability from schedules to the existing route panel. |

Original schedule PDFs are in `sources/route_schedules/`. The two O3 manifests overlap, covering 102 distinct publications. The complete 228-publication archive is now also included, with local paths and hashes in `data/routes/full_schedule_archive/source_manifest.json`; archive size does not imply complete historical coverage. City-pair workbooks for November 2019, November 2023 and June 2026 are also saved there. [Provenance](data/routes/provenance.json) records copied inputs and their fingerprints.

## The regional extension

The previous top-20 panel represented TruJet on only two airport pairs. The extension instead selects routes from TruJet's recovered filings and includes **all recorded competing airlines** on those routes. It covers **265 route-months on 30 distinct pairs**, over April 2019–February 2020 and November 2021–January 2022. These are 14 covered months, with a gap between periods.

Processing in [analyse_routes.py](analyse_routes.py):

1. Map station names to airport codes, retaining documented spelling aliases. Keep Goa Dabolim and Mopa distinct; the regional extension predates Mopa.
2. Restrict every row to its stated validity and season boundaries. Expand weekday masks into calendar dates. Include both seasonal filings when a month crosses a season boundary.
3. Deduplicate by airline, flight number, date and directed leg. Count departures at both airports, pooling both directions for each pair. Apply the documented April 2019 Jet/JetLite cessation date.
4. Compare departures with arrival records **by airline and directed leg**. Exclude unresolved extraction issues and discrepancies exceeding 5% of departures. **234 of 265** retained regional observations match exactly.
5. Divide each airline's scheduled flights by the recorded route total. Sum squared percentage shares for brand HHI. Check flight totals, shares and HHI arithmetic.

For example, [TruJet's winter 2019 report](https://public-prd-dgca.s3.ap-south-1.amazonaws.com/InventoryList/airOperation/certification/scheduled/domestic/TruJet_WS2019.pdf), PDF pp. 2 and 4, lists daily Chennai–Salem flight **2T531** and the reverse **2T532**, valid 27 October 2019–28 March 2020. Each contributes 30 November departures. Among recovered filings, TruJet has `60/60 = 100%` frequency share and brand HHI is `100² = 10,000`.

In November 2019, **22 of 30** pairs in TruJet's filing pass the screen. It supplies at least half the recorded frequency on **17**, or **77.27%** of the screened pairs. Fourteen have only TruJet in recovered schedules. Eight remain unassessed. This supports a local role, without identifying actual operated flights or proving a monopoly over all travel alternatives.

## Outputs and interpretation

- [Entrant route-months](results/route_evidence/entrant_route_months.csv): **1,300** airline-route-month observations; TruJet 265 on 30 pairs, Vistara 613 on 20, Akasa 422 on 18.
- [Route trajectories](results/route_evidence/entrant_route_trajectories.csv): first/last covered shares and consecutive covered months. Gaps break runs and do not establish exit. The Vistara trajectory summary excludes its partial November 2024 merger month.
- [Regional coverage](results/route_evidence/regional_coverage.csv): retained and excluded observations with reasons.
- [Regional competitor shares](results/route_evidence/regional_airline_shares.csv): the denominator and every recorded airline's contribution.
- [Route passenger demand](results/route_evidence/served_route_passenger_demand.csv): both-direction totals for 4,964 covered month/pairs relevant to the entrants. Missing directions are flagged.
- [Worked examples](results/route_evidence/worked_examples.csv) and [checks](results/route_evidence/verification.json).

The samples cover different years and markets. Compare firms within a named route/month, or a firm's share over time on the same route; do not rank their whole networks from these samples. The major-route input retains its original pooled endpoint screen; the regional extension uses the stricter directed check. Twelve overlapping route-month totals agree.

Approved schedules can differ from actual operation, especially during the pandemic. Entirely missing carrier filings can escape endpoint checks, so shares describe recovered schedules. City-pair passenger totals have no airline split: **multiplying them by frequency shares would not recover airline passengers or load factors**. Brand HHI also needs ownership grouping for firm-concentration analysis.

For the O3 outputs, Chennai–Hyderabad in February–March 2022 is excluded because the archived schedules continue listing TruJet after its cessation. TruJet's usable route series ends in January 2022. This avoids treating an unexpired schedule as continuing service.

Reproduce with `python3 reproduce.py` from the repository root. The major-route panel is rebuilt from the full saved extraction, and the regional analysis selects its 34 filings from that same extraction. `python3 reproduce.py --from-pdfs` regenerates the extraction from the original PDFs using Poppler. It retains the earlier national comparisons as background calculations and uses the route hypothesis as H1 in the consolidated results.
