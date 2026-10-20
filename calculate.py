"""Reproduce the case-study tables using Python's standard library.

Run: python3 calculate.py
All inputs and outputs are contained in this folder. No network calls.
"""

import csv
import hashlib
import json
from collections import defaultdict
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 35
D = Decimal
ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
AIRLINES = ("Vistara", "TruJet", "Akasa Air")
CUTOFF = 2026 * 12 + 6


def index(row):
    return int(row["year"]) * 12 + int(row["month"]) - 1


def label(month):
    year, m = divmod(month, 12)
    return f"{year:04d}-{m + 1:02d}"


def percent(numerator, denominator):
    return 100 * D(numerator) / D(denominator)


def write_csv(name, rows):
    with (RESULTS / name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def serialise(value):
    if isinstance(value, D):
        return float(value)
    raise TypeError(type(value).__name__)


def main():
    RESULTS.mkdir(exist_ok=True)
    import rebuild_routes
    rebuild_routes.build_monthly()
    raw_path = ROOT / "data/carrier_monthly.csv"
    with raw_path.open() as stream:
        rows = [r for r in csv.DictReader(stream)
                if r["service_type"] == "scheduled_domestic" and index(r) <= CUTOFF]
    keys = [(r["airline"], index(r)) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate airline-month in input")
    national = defaultdict(int)
    for row in rows:
        national[index(row)] += int(row["passengers"])
    inputs = json.loads((ROOT / "data/financial_inputs.json").read_text())
    threshold = D(inputs["analyst_assumptions"]["national_share_threshold_percent"])
    age_results, summaries, monthly = [], [], []
    for airline in AIRLINES:
        own = sorted([r for r in rows if r["airline"] == airline and int(r["passengers"]) > 0], key=index)
        start, end = index(own[0]), index(own[-1])
        by_month = {index(r): r for r in own}
        age_values = {}
        for age_year in (1, 3):
            first = start + (age_year - 1) * 12
            months = range(first, first + 12)
            selected = [by_month[m] for m in months if m in by_month]
            if len(selected) != 12:
                raise ValueError(f"Incomplete comparison window: {airline}, age year {age_year}")
            passengers = sum(int(r["passengers"]) for r in selected)
            market = sum(national[m] for m in months)
            rpk = sum(D(r["passenger_km"]) for r in selected)
            ask = sum(D(r["seat_km"]) for r in selected)
            result = {"airline": airline, "age_year": age_year,
                      "first_month": label(first), "last_month": label(first + 11),
                      "observations": len(selected), "airline_passengers": passengers,
                      "all_airline_passengers": market, "rpk_thousand": rpk,
                      "ask_thousand": ask, "passenger_share_percent": percent(passengers, market),
                      "load_factor_percent": percent(rpk, ask)}
            age_results.append(result)
            age_values[age_year] = result
        current = best = above_count = 0
        best_start = best_end = None
        for month in range(start, end + 1):
            row = by_month.get(month)
            share = percent(int(row["passengers"]), national[month]) if row else None
            above = share is not None and share >= threshold
            current = current + 1 if above else 0
            above_count += int(above)
            if current > best:
                best = current
                best_start, best_end = month - current + 1, month
            monthly.append({"airline": airline, "month": label(month),
                            "age_month": month - start + 1,
                            "airline_passengers": int(row["passengers"]) if row else "",
                            "all_airline_passengers": national.get(month, ""),
                            "passenger_share_percent": share if share is not None else "",
                            "rpk_thousand": row["passenger_km"] if row else "",
                            "ask_thousand": row["seat_km"] if row else "",
                            "status": "observed_positive_traffic" if row else "no_positive_traffic_observation"})
        first, third = age_values[1], age_values[3]
        summaries.append({"airline": airline, "first_positive_month": label(start),
                          "last_positive_month_by_cutoff": label(end),
                          "positive_passenger_months": len(own),
                          "inclusive_calendar_span_months": end - start + 1,
                          "outcome": {"Vistara": "merged", "TruJet": "ceased operations", "Akasa Air": "operating at cutoff"}[airline],
                          "followup_ends_at_cutoff": airline == "Akasa Air",
                          "year1_share_percent": first["passenger_share_percent"],
                          "year3_share_percent": third["passenger_share_percent"],
                          "share_change_percentage_points": third["passenger_share_percent"] - first["passenger_share_percent"],
                          "share_growth_percent": percent(third["passenger_share_percent"] - first["passenger_share_percent"], first["passenger_share_percent"]),
                          "passenger_growth_year1_to_year3_percent": percent(third["airline_passengers"] - first["airline_passengers"], first["airline_passengers"]),
                          "ask_growth_year1_to_year3_percent": percent(third["ask_thousand"] - first["ask_thousand"], first["ask_thousand"]),
                          "year1_load_factor_percent": first["load_factor_percent"],
                          "year3_load_factor_percent": third["load_factor_percent"],
                          "load_factor_change_percentage_points": third["load_factor_percent"] - first["load_factor_percent"],
                          "share_threshold_percent": threshold,
                          "months_at_or_above_threshold": above_count,
                          "longest_consecutive_months_at_or_above_threshold": best,
                          "longest_run_start": label(best_start) if best_start is not None else "",
                          "longest_run_end": label(best_end) if best_end is not None else ""})
    financial_years, financial_changes, scenarios = [], [], []
    for name in ("Vistara", "Akasa Air"):
        records = sorted([r for r in inputs["records"] if r["airline"] == name], key=lambda r: r["financial_year"])
        for r in records:
            revenue, pat = D(r["operating_income"]), D(r["profit_after_tax"])
            financial_years.append({**r, "net_profit_margin_percent": percent(pat, revenue)})
        old, new = records
        r0, r1 = D(old["operating_income"]), D(new["operating_income"])
        p0, p1 = D(old["profit_after_tax"]), D(new["profit_after_tax"])
        financial_changes.append({"airline": name,
                                  "earlier_financial_year": old["financial_year"], "later_financial_year": new["financial_year"],
                                  "operating_income_growth_percent": percent(r1 - r0, r0),
                                  "net_loss_magnitude_change_percent": percent(abs(p1) - abs(p0), abs(p0)),
                                  "earlier_net_margin_percent": percent(p0, r0),
                                  "later_net_margin_percent": percent(p1, r1),
                                  "net_margin_change_percentage_points": percent(p1, r1) - percent(p0, r0),
                                  "operating_margin_change_percentage_points": D(new["operating_margin_percent"]) - D(old["operating_margin_percent"])})
        for fraction in inputs["analyst_assumptions"]["incremental_revenue_contribution_fractions"]:
            contribution = D(fraction)
            extra = -p1 / contribution
            scenarios.append({"airline": name, "base_financial_year": new["financial_year"],
                              "base_operating_income_crore": r1, "base_profit_after_tax_crore": p1,
                              "assumed_incremental_contribution_fraction": contribution,
                              "extra_revenue_to_close_profit_gap_crore": extra,
                              "extra_revenue_percent_of_base": percent(extra, r1),
                              "scenario_total_revenue_crore": r1 + extra,
                              "interpretation": inputs["analyst_assumptions"]["scenario_conditions"]})
    routes = inputs["trujet_udan"]
    regional = {**routes, "commencement_rate_percent": percent(routes["routes_commenced"], routes["routes_awarded"]),
                "operational_march2023_as_percent_of_ever_commenced": percent(routes["routes_operational_march_2023"], routes["routes_commenced"])}
    hypotheses = [
        {"id": "H1", "hypothesis": "Each entrant increased its national passenger share from its first to its third operating year.",
         "comparison": "Check whether the year-3 minus year-1 passenger-share change is positive for each airline.",
         "results": [{"airline": r["airline"], "change_percentage_points": r["share_change_percentage_points"], "supported_in_this_comparison": r["share_change_percentage_points"] > 0} for r in summaries],
         "qualification": "Descriptive check on three selected cases; calendar conditions differ and the first year includes the partial launch month."},
        {"id": "H2", "hypothesis": "Revenue growth was accompanied by an improvement in net profit margin.",
         "comparison": "Among the two airlines with comparable financial pairs, check whether positive revenue growth coincides with a positive margin change.",
         "results": [{"airline": r["airline"], "revenue_growth_percent": r["operating_income_growth_percent"], "margin_change_percentage_points": r["net_margin_change_percentage_points"], "supported_in_this_comparison": r["net_margin_change_percentage_points"] > 0} for r in financial_changes],
         "qualification": "One annual change per airline, in different years; not an estimate of scale economies. TruJet lacks comparable financial inputs."}
    ]
    for name, table in [("monthly_panel.csv", monthly), ("operating_year_comparisons.csv", age_results),
                        ("airline_summary.csv", summaries), ("financial_year_results.csv", financial_years),
                        ("financial_changes.csv", financial_changes), ("break_even_scenarios.csv", scenarios),
                        ("trujet_udan_results.csv", [regional])]:
        write_csv(name, table)
    result = {"cutoff": "2026-07", "input_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
              "national_months_with_positive_traffic": sum(v > 0 for v in national.values()),
              "operating_year_comparisons": age_results, "airline_summary": summaries,
              "financial_years": financial_years, "financial_changes": financial_changes,
              "regional_results": regional, "break_even_scenarios": scenarios, "hypotheses": hypotheses}
    if (ROOT / "data/routes/regional_schedule_manifest.json").exists():
        import analyse_routes
        analyse_routes.main()
        route_results = json.loads((RESULTS / "route_evidence/verification.json").read_text())
        result["national_growth_background_check"] = result["hypotheses"][0]
        result["hypotheses"][0] = {
            "id": "H1", **route_results["H1"],
            "qualification": "Recovered schedule frequencies on 22 screened routes out of 30 in the filing; no passenger-share or actual-monopoly claim."
        }
        result["route_evidence"] = {
            "regional_route_months": route_results["regional_route_months"],
            "regional_unique_routes": route_results["regional_unique_routes"],
            "coverage_by_airline": route_results["coverage_by_airline"],
            "details": "results/route_evidence/verification.json"
        }
    (RESULTS / "calculations.json").write_text(json.dumps(result, default=serialise, indent=2) + "\n")
    for r in summaries:
        print(f"{r['airline']}: share {r['year1_share_percent']:.2f}% -> {r['year3_share_percent']:.2f}%; year-3 PLF {r['year3_load_factor_percent']:.2f}%; longest >=5% run {r['longest_consecutive_months_at_or_above_threshold']} months ({r['longest_run_start']} to {r['longest_run_end']})")
    for r in financial_changes:
        print(f"{r['airline']}: revenue growth {r['operating_income_growth_percent']:.2f}%; net-margin change {r['net_margin_change_percentage_points']:.2f} percentage points")


if __name__ == "__main__":
    main()
