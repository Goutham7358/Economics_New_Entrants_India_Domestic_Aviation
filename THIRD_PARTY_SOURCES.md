# Source provenance and attribution

## Passenger datasets

The included `data/carrier_monthly.csv` and `data/routes/domestic_route_monthly.csv` are DGCA-derived datasets from **mkubicek/india-aviation-stats**, pinned to commit `16770ac59dae61ce7b80fd8bd67dd7f4cef280a6`:

- [Carrier data](https://github.com/mkubicek/india-aviation-stats/blob/16770ac59dae61ce7b80fd8bd67dd7f4cef280a6/data/processed/carrier_monthly.csv).
- [Route data](https://github.com/mkubicek/india-aviation-stats/blob/16770ac59dae61ce7b80fd8bd67dd7f4cef280a6/data/processed/domestic_route_monthly.csv).
- Included upstream [MIT licence](sources/india_aviation_stats_LICENSE.txt), [README](sources/india_aviation_stats_README.md), [methodology](sources/india_aviation_stats_METHODOLOGY.md) and [data dictionary](sources/india_aviation_stats_data_dictionary.md).

The source README is an archived upstream document; its relative links refer to that upstream repository. Selected original DGCA workbooks are included and checked directly, as described in [SOURCE_CHECKS.md](verification/SOURCE_CHECKS.md).

## Schedule archive

The [full archive manifest](data/routes/full_schedule_archive/source_manifest.json) records **228 original publications**, including their local paths, original URLs, hashes, seasons and extraction status. All PDFs are stored in `sources/route_schedules/`. Some archived formats do not supply usable rows; archive size does not imply complete coverage.

[rebuild_routes.py](rebuild_routes.py) is adapted from `monthly_route_hhi.py` in the original economics project. Its paths now point inside this repository, it stops at July 2026, and iteration is sorted for reproducibility. The included extracted rows preserve PDF/page/row references. The regional analysis uses these same full-archive rows, selected by its 34-file manifest. Reference snapshots are retained and compared with the rebuilt tables.

[operation_adjustments.json](sources/operation_adjustments.json) records the cessation and merger conventions. Supporting [Jet Airways closure](sources/airline_closures_Lok_Sabha_2023.pdf) and [Go First suspension](sources/gofirst_suspension_Lok_Sabha_2023.pdf) parliamentary replies are included. Air India sources for [Vistara flight conversion](sources/air_india_vistara_flight_conversion_2024_verified_extract.md) and [AIX Connect integration](sources/air_india_express_aix_merger_2024_verified_extract.md) are recorded in verified source notes with official URLs.

## Case-study documents

The [document manifest](verification/source_manifest.json) and [source checks](verification/SOURCE_CHECKS.md) identify the downloaded company, audit, tribunal and press documents and the passages used. Original documents retain their authorship and rights. The dataset's MIT licence applies to its upstream material; it does not relicense the company reports, press articles, government documents or syllabus.

[reproduction_inputs.json](verification/reproduction_inputs.json) pins every included analysis input and source file. Interpretations, manual airport-name mappings and classroom scenario assumptions remain identified in the study and scripts.
