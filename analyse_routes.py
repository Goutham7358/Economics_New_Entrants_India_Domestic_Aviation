"""Add route competition evidence using only inputs stored in this folder.

Regional extension: TruJet's published routes, Apr 2019-Feb 2020 and
Nov 2021-Jan 2022. Existing top-20 monthly series provide additional cases.
Schedule frequencies are estimates of published supply, not passenger shares.
Run: python3 analyse_routes.py
"""

import calendar
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data/routes"
OUT = ROOT / "results/route_evidence"
ARCHIVE = DATA / "full_schedule_archive"
REBUILT = ROOT / "results/route_input_rebuild"
FOCAL = {"Vistara", "TruJet", "Akasa Air"}
ALIASES = {
    "NASIK": "NASHIK", "JALGOAN": "JALGAON", "PORBANDER": "PORBANDAR",
    "KADAPA": "CUDDAPAH", "RAJAHMUNRY": "RAJAHMUNDRY", "RAJAMUNDRY": "RAJAHMUNDRY",
    "TIRUPATHI": "TIRUPATI", "VIJAYWADA": "VIJAYAWADA", "GOA (MOPA)": "GOA MOPA",
    "BHUBANESHWAR": "BHUBNESHWAR", "BHUBANESWAR": "BHUBNESHWAR", "HUBLI": "HUBALI",
    "CALICUT": "KOZHIKODE", "TRIVANDRUM": "TRIVANDRUM", "COCHIN": "KOCHI",
    "CHENNAI (MADRAS)": "CHENNAI", "CHENNAI(MADRAS)": "CHENNAI",
    "MUMBAI (BOMBAY)": "MUMBAI", "BOMBAY": "MUMBAI", "BENGALURU": "BANGALORE",
    "KOLKATA (CALCUTTA)": "KOLKATA", "CALCUTTA": "KOLKATA",
}


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def write_csv(name, rows, fields=None):
    path = OUT / name
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def airport(code):
    # GOA is a legacy code in the pre-Mopa filings used in this extension.
    return "GOI" if code == "GOA" else code


def pair(a, b):
    return "-".join(sorted((a, b)))


def canonical_flight(flight):
    match = re.fullmatch(r"([A-Z0-9]{2})(\d+)([A-Z]?)", flight)
    return match[1] + str(int(match[2])) + match[3] if match else flight


def main():
    OUT.mkdir(exist_ok=True)
    if not (REBUILT / "monthly_route_hhi.csv").exists():
        import rebuild_routes
        rebuild_routes.build_monthly()
    mapping = {r["station_city"].upper(): r["iata"] for r in read_csv(DATA / "station_airport_codes.csv")}
    mapping["JAISALMER"] = "JSA"
    def station_code(station):
        key = " ".join(station.upper().split())
        return mapping.get(ALIASES.get(key, key), "")
    inventory = json.loads((DATA / "regional_schedule_manifest.json").read_text())
    inv = {r["filename"]: r for r in inventory}
    for item in inventory:
        path = ROOT / item["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Source hash mismatch: " + path.name)
    rows = [r for r in read_csv(ARCHIVE / "source_schedule_rows.csv") if r["source_file"] in inv]
    relevant = []
    unmapped = Counter()
    for original in rows:
        station = station_code(original["station"]) or original["station_iata"]
        if not station:
            unmapped[(original["airline"], original["station"])] += 1
            continue
        r = dict(original)
        r["station_iata"] = station
        r["other_airport"] = airport(r["other_airport"])
        r["route"] = pair(station, r["other_airport"])
        item = inv[r["source_file"]]
        r["lo"] = max(date.fromisoformat(r["effective_from"]), date.fromisoformat(item["season_start"]))
        r["hi"] = min(date.fromisoformat(r["effective_to"]), date.fromisoformat(item["season_end"]))
        relevant.append(r)
    if any(airline == "TruJet" for airline, _ in unmapped):
        raise ValueError("A TruJet station is unmapped")
    issues_by_season = defaultdict(set)
    for issue in read_csv(ARCHIVE / "extraction_issues.csv"):
        if issue["file"] not in inv:
            continue
        station = station_code(issue["station"])
        item = inv[issue["file"]]
        if station:
            for endpoint in re.findall(r"\b[A-Z]{3}\b", issue["text"]):
                issues_by_season[(item["year"], item["season"])].add(pair(station, airport(endpoint)))
    months = [f"2019-{m:02d}" for m in range(4, 13)] + ["2020-01", "2020-02", "2021-11", "2021-12", "2022-01"]
    summaries, shares, coverage, regional_months, used_rows = [], [], [], [], set()
    for month in months:
        first = date.fromisoformat(month + "-01")
        last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
        selected = [r for r in relevant if r["lo"] <= last and r["hi"] >= first]
        active_seasons = {(int(r["season_year"]), r["season"]) for r in selected}
        candidates = {r["route"] for r in selected if r["airline"] == "TruJet" and r["direction"] == "departure"}
        events = {"departure": set(), "arrival": set()}
        refs = defaultdict(set)
        for r in selected:
            if r["route"] not in candidates:
                continue
            if r["direction"] == "departure":
                origin, destination = r["station_iata"], r["other_airport"]
            else:
                origin, destination = r["other_airport"], r["station_iata"]
            start, end = max(first, r["lo"]), min(last, r["hi"])
            for delta in range((end - start).days + 1):
                day = start + timedelta(days=delta)
                if str(day.isoweekday()) not in r["operating_days"]:
                    continue
                if r["airline"] in {"Jet Airways", "JetLite"} and day > date(2019, 4, 17):
                    continue
                key = (r["route"], r["airline"], canonical_flight(r["flight_number"]), origin, destination, day.isoformat())
                events[r["direction"]].add(key)
                refs[r["route"]].add(r["source_file"])
                used_rows.add((r["source_file"], r["source_page"], r["source_row"], r["station"], r["direction"]))
        counts = {direction: defaultdict(Counter) for direction in events}
        for direction, identities in events.items():
            for route, airline, flight, origin, destination, day in sorted(identities):
                counts[direction][route][(airline, origin, destination)] += 1
        passed_count = 0
        for route in sorted(candidates):
            departures = counts["departure"][route]
            arrivals = counts["arrival"][route]
            total = sum(departures.values())
            difference = sum(abs(departures[k] - arrivals[k]) for k in departures.keys() | arrivals.keys())
            diff_percent = 100 * difference / total if total else 100
            a, b = route.split("-")
            by_airline = Counter()
            directions = defaultdict(Counter)
            for (airline, origin, destination), n in departures.items():
                by_airline[airline] += n
                directions[airline][origin] += n
            reasons = []
            if any(route in issues_by_season[season] for season in active_seasons):
                reasons.append("unresolved extraction issue on route")
            if diff_percent > 5:
                reasons.append("directed airline endpoint-count discrepancy exceeds 5%")
            if not sum(n for (airline, origin, destination), n in departures.items() if origin == a) or not sum(n for (airline, origin, destination), n in departures.items() if origin == b):
                reasons.append("both departure directions not represented")
            if by_airline["TruJet"] == 0:
                reasons.append("no TruJet departure within month")
            coverage.append({"month": month, "route": route, "included": not reasons,
                             "reason": "; ".join(reasons), "endpoint_difference_pct": round(diff_percent, 8),
                             "recovered_carrier_count": len(by_airline), "trujet_scheduled_flights": by_airline["TruJet"]})
            if reasons:
                continue
            passed_count += 1
            hhi = 10000 * sum((n / total) ** 2 for n in by_airline.values())
            route_record = {"month": month, "route": route, "airport_a": a, "airport_b": b,
                            "route_flights": total, "carrier_count": len(by_airline),
                            "brand_frequency_hhi": round(hhi, 8), "endpoint_difference_pct": round(diff_percent, 8),
                            "endpoint_count_exact_match": difference == 0,
                            "source_pdf_count": len(refs[route]),
                            "basis": "approved departure frequency, both directions; recovered filings",
                            "source_scope": "TruJet regional extension"}
            regional_months.append(route_record)
            for airline, flights in sorted(by_airline.items()):
                shares.append({"month": month, "route": route, "airline": airline,
                               "flights_a_to_b": directions[airline][a], "flights_b_to_a": directions[airline][b],
                               "scheduled_flights": flights, "route_flights": total,
                               "frequency_share_pct": round(100 * flights / total, 10),
                               "brand_hhi_contribution": round(10000 * (flights / total) ** 2, 10)})
        own = [r for r in shares if r["month"] == month and r["airline"] == "TruJet"]
        summaries.append({"month": month, "routes_in_trujet_filing": len(candidates),
                          "routes_passing_screen": passed_count,
                          "routes_with_trujet_share_at_least_50_percent": sum(float(r["frequency_share_pct"]) >= 50 for r in own),
                          "routes_with_only_trujet_in_recovered_schedules": sum(float(r["frequency_share_pct"]) == 100 for r in own)})
    write_csv("regional_route_months.csv", regional_months)
    write_csv("regional_airline_shares.csv", shares)
    write_csv("regional_coverage.csv", coverage)
    write_csv("regional_monthly_summary.csv", summaries)
    raw_used = [r for r in rows if (r["source_file"], r["source_page"], r["source_row"], r["station"], r["direction"]) in used_rows]
    write_csv("regional_source_rows_used.csv", raw_used)
    # Combine overlapping route-months only when their departure counts agree.
    market = {(r["month"], r["route"]): {"route_flights": int(r["scheduled_flights_both_directions"]),
              "brand_frequency_hhi": r["brand_frequency_hhi"], "endpoint_difference_pct": r["counterpart_count_difference_pct"],
              "source_scope": "top20 route sample"} for r in read_csv(REBUILT / "monthly_route_hhi.csv")}
    all_shares = {(r["month"], r["route"], r["airline"]): r for r in read_csv(REBUILT / "monthly_carrier_route_shares.csv")}
    overlap_checks = 0
    for r in regional_months:
        key = (r["month"], r["route"])
        if key in market:
            if market[key]["route_flights"] != r["route_flights"]:
                raise ValueError(f"Different counts on overlapping route-month {key}")
            overlap_checks += 1
        market[key] = r
    for r in shares:
        all_shares[(r["month"], r["route"], r["airline"])] = r
    regional_keys = {(r["month"], r["route"]) for r in regional_months}
    cessation_affected = {(r["month"], r["route"]) for r in all_shares.values()
                          if r["airline"] == "TruJet" and r["month"] >= "2022-02"}
    focal_rows = []
    for key, r in sorted(all_shares.items()):
        if r["airline"] not in FOCAL:
            continue
        if (r["month"], r["route"]) in cessation_affected:
            continue
        if r["airline"] == "TruJet" and (r["month"], r["route"]) not in regional_keys:
            continue
        m = market[(r["month"], r["route"])]
        focal_rows.append({"month": r["month"], "route": r["route"], "airline": r["airline"],
                           "scheduled_flights": r["scheduled_flights"], "route_flights": r["route_flights"],
                           "frequency_share_pct": r["frequency_share_pct"],
                           "brand_frequency_hhi": m["brand_frequency_hhi"],
                           "endpoint_difference_pct": m["endpoint_difference_pct"], "source_scope": m["source_scope"]})
    write_csv("entrant_route_months.csv", focal_rows)
    by_airline_route = defaultdict(list)
    for r in focal_rows:
        if r["airline"] == "Vistara" and r["month"] >= "2024-11":
            continue  # Its last brand month is partial because of the merger.
        by_airline_route[(r["airline"], r["route"])].append(r)
    trajectories = []
    for (airline, route), rr in sorted(by_airline_route.items()):
        rr.sort(key=lambda r: r["month"])
        previous = None
        current = longest = 0
        for r in rr:
            year, month = map(int, r["month"].split("-"))
            number = year * 12 + month
            current = current + 1 if previous is not None and number == previous + 1 else 1
            previous = number
            longest = max(longest, current)
        trajectories.append({"airline": airline, "route": route, "observed_months": len(rr),
                             "first_covered_month": rr[0]["month"], "last_covered_month": rr[-1]["month"],
                             "first_frequency_share_pct": rr[0]["frequency_share_pct"],
                             "last_frequency_share_pct": rr[-1]["frequency_share_pct"],
                             "change_percentage_points": round(float(rr[-1]["frequency_share_pct"]) - float(rr[0]["frequency_share_pct"]), 8),
                             "longest_consecutive_covered_months_with_service": longest,
                             "interpretation": "Incomplete schedule observations; gaps break runs and do not establish exit. Different periods are not age-matched."})
    write_csv("entrant_route_trajectories.csv", trajectories)
    # Actual city-pair passenger demand is a separate measure with no airline split.
    focus_routes = {r["route"] for r in focal_rows}
    traffic = defaultdict(Counter)
    for r in read_csv(DATA / "domestic_route_monthly.csv"):
        month = f"{int(r['year']):04d}-{int(r['month']):02d}"
        route = pair(r["origin"], r["destination"])
        if month <= "2026-07" and route in focus_routes:
            traffic[(month, route)][r["origin"]] += int(r["passengers"])
    passenger_rows = []
    for (month, route), values in sorted(traffic.items()):
        a, b = route.split("-")
        passenger_rows.append({"month": month, "route": route, "passengers_a_to_b": values.get(a, ""),
                               "passengers_b_to_a": values.get(b, ""), "both_directions_reported": a in values and b in values,
                               "passengers_both_directions": sum(values.values()), "airline_split_available": False})
    write_csv("served_route_passenger_demand.csv", passenger_rows)
    examples = []
    for airline, month, route in [("TruJet", "2019-11", "MAA-SXV"), ("TruJet", "2019-11", "CDP-MAA"),
                                   ("Vistara", "2023-11", "BOM-DEL"), ("Akasa Air", "2023-11", "BOM-DEL"),
                                   ("Akasa Air", "2026-06", "DEL-PNQ")]:
        result = next((r for r in focal_rows if r["airline"] == airline and r["month"] == month and r["route"] == route), None)
        if result:
            examples.append({**result, "all_airline_route_passengers": sum(traffic.get((month, route), {}).values())})
    write_csv("worked_examples.csv", examples)
    by_key = defaultdict(list)
    for r in shares:
        by_key[(r["month"], r["route"])].append(r)
    for r in regional_months:
        ss = by_key[(r["month"], r["route"])]
        if sum(int(s["scheduled_flights"]) for s in ss) != r["route_flights"]:
            raise ValueError("Frequency total mismatch")
        if abs(sum(float(s["frequency_share_pct"]) for s in ss) - 100) > 1e-7:
            raise ValueError("Share total mismatch")
        if abs(sum(float(s["brand_hhi_contribution"]) for s in ss) - r["brand_frequency_hhi"]) > 1e-6:
            raise ValueError("HHI mismatch")
    hypothesis_month = next(r for r in summaries if r["month"] == "2019-11")
    meta = {"cutoff": "2026-07", "regional_months": len(months), "regional_original_pdfs": len(inventory),
            "regional_route_months": len(regional_months), "regional_unique_routes": len({r["route"] for r in regional_months}),
            "regional_exact_endpoint_matches": sum(r["endpoint_count_exact_match"] for r in regional_months),
            "overlap_count_checks": overlap_checks, "focal_route_months": len(focal_rows),
            "excluded_top20_route_months_with_published_trujet_after_cessation": sorted([list(k) for k in cessation_affected]),
            "coverage_by_airline": {a: {"observations": sum(r["airline"] == a for r in focal_rows),
                "routes": len({r["route"] for r in focal_rows if r["airline"] == a})} for a in sorted(FOCAL)},
            "H1": {"hypothesis": "TruJet supplied at least half of scheduled frequencies on more than half its covered routes in November 2019.",
                   **hypothesis_month, "supported_in_covered_sample": hypothesis_month["routes_with_trujet_share_at_least_50_percent"] > hypothesis_month["routes_passing_screen"] / 2},
            "unmapped_nonfocal_stations": [{"airline": a, "station": s, "rows": n} for (a, s), n in sorted(unmapped.items())],
            "limits": ["Approved schedules, not actual departures or passenger shares.",
                       "At most 5% sum of directed airline endpoint-count differences; excludes unresolved route extraction issues.",
                       "Matching endpoints cannot detect a carrier missing from both airport reports or an entirely missing filing.",
                       "Top20 series are a selected major-route sample; the extension covers TruJet's recovered regional filings.",
                       "Route sets and periods differ; no cross-airline network ranking or complete entry-age route comparison.",
                       "City-pair passengers cover all airlines; cannot be multiplied by frequency shares to recover airline passengers.",
                       "Post-2020 schedules can differ substantially from actual operation during the pandemic."]}
    (OUT / "verification.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Regional extension: {len(regional_months)} route-months, {meta['regional_unique_routes']} routes, {len(months)} covered months; {meta['regional_exact_endpoint_matches']} exact endpoint matches.")
    print(f"Combined focal airline-route-months: {len(focal_rows)}. H1: {hypothesis_month['routes_with_trujet_share_at_least_50_percent']}/{hypothesis_month['routes_passing_screen']} covered routes.")


if __name__ == "__main__":
    main()
