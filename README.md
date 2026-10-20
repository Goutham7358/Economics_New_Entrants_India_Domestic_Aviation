# Economics_New_Entrants_India_Domestic_Aviation

A managerial economics case study of **Vistara, TruJet and Akasa Air**, with an observation cutoff of **31 July 2026**. It compares their role on routes served, financial performance, funding decisions and outcomes.

Start with [CASE_STUDY.md](CASE_STUDY.md). [ACTIONS_AND_FUNDING.md](ACTIONS_AND_FUNDING.md) explains the decisions behind cessation, continued operation and merger. [ROUTE_DATA.md](ROUTE_DATA.md) explains the route evidence and its coverage.

## Reproduce the results

Requirements: **Python 3.10 or later**. The default workflow uses only the Python standard library, with no downloads or package installation.

```bash
git clone https://github.com/Goutham7358/Economics_New_Entrants_India_Domestic_Aviation.git
cd Economics_New_Entrants_India_Domestic_Aviation
python3 reproduce.py
```

The command verifies the saved inputs, rebuilds the major-route tables, calculates the airline comparisons and regional results, then verifies the source passages, arithmetic and figures quoted in the case study. It writes outputs under `results/` and check records under `verification/`. It needs no files from the original economics project.

To also regenerate the schedule extraction from the **228 saved original PDFs**, install Poppler's `pdftotext` command and run:

```bash
python3 reproduce.py --from-pdfs
```

The PDF option checks that the regenerated extraction matches the pinned input fingerprints. The default command uses the included extraction, with source PDF/page/row references. Unsupported historical table formats remain labelled in the archive manifest; they are not treated as complete monthly coverage.

## Included files

| Location | Contents |
|---|---|
| `sources/` | Original schedule PDFs, company reports, investor-call transcript, funding releases, tribunal orders, CAG audit, DGCA workbooks and syllabus; supporting source notes and upstream attribution. |
| `data/` | Pinned passenger data, financial inputs, airport mappings, schedule extraction and reference snapshots. |
| `rebuild_routes.py` | PDF extraction and major-route frequency calculations, using local files only. |
| `calculate.py`, `analyse_routes.py` | Financial, national-background and regional-route calculations. |
| `verify.py`, `verify_routes.py`, `verify_reproduction.py` | Input fingerprints, source passages, original workbook cells, route reconstruction, reference-table comparisons and headline figures. |
| `results/` | Rebuilt route tables, financial calculations, hypotheses and worked examples. |
| `verification/` | Source URLs, SHA-256 fingerprints, text/OCR extracts, reviewed page images and machine-readable check results. |

Selected outputs:

- [Consolidated calculations and hypotheses](results/calculations.json).
- [Major-route monthly HHI](results/route_input_rebuild/monthly_route_hhi.csv): **1,114** covered route-months across 20 routes and 64 months, April 2019–July 2026.
- [Entrant route observations](results/route_evidence/entrant_route_months.csv): **1,300** airline-route-months, including the TruJet regional extension.
- [Financial changes](results/financial_changes.csv) and [break-even scenarios](results/break_even_scenarios.csv).
- [Source checks](verification/SOURCE_CHECKS.md) and [reproduction checks](verification/reproduction_results.json).

## Interpretation

Route shares and HHI measure **approved scheduled frequency**, combining both directions. They do not measure airline passenger shares or actual operated flights. The archive does **not** supply a complete monthly route panel for 2015–2026. Missing coverage is retained explicitly.

Passenger CSVs are pinned third-party normalisations of DGCA returns; selected original workbooks are included for verification. The workflow reproduces from those snapshots rather than downloading every historical DGCA workbook. Funding proposals, completed investments and reported estimates have separate labels. Financial scenarios use stated assumptions. The strategic conclusions are arguments from documented evidence; arithmetic alone does not establish causation.

[Third-party provenance and attribution](THIRD_PARTY_SOURCES.md).
