"""Verify route source hashes, original city-pair totals and worked schedules."""

import calendar
import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def worksheet_cells(path):
    with zipfile.ZipFile(path) as archive:
        strings = ["".join(s.itertext()) for s in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        tree = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        cells = {}
        for cell in tree.findall(".//m:c", NS):
            value = cell.find("m:v", NS)
            if value is not None:
                cells[cell.get("r")] = strings[int(value.text)] if cell.get("t") == "s" else value.text
        return cells


def main():
    manifest = json.loads((ROOT / "verification/route_source_manifest.json").read_text())
    for record in manifest["documents"] + manifest["citypair_workbooks"]:
        path = ROOT / record["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Route source hash mismatch: " + path.name)
    data = ROOT / "data/routes"
    if hashlib.sha256((data / "domestic_route_monthly.csv").read_bytes()).hexdigest() != "400e1b215682ded55d74168a8ef00d72016991d5c3f34ac8ca46eb555049b98e":
        raise ValueError("City-pair input changed")
    demand = {(r["month"], r["route"]): r for r in read_csv(ROOT / "results/route_evidence/served_route_passenger_demand.csv")}
    demand_checks = []
    for record in manifest["citypair_workbooks"]:
        cells = worksheet_cells(ROOT / record["path"])
        for check in record["checks"]:
            row = check["row"]
            outwards, inwards = int(cells[f"D{row}"]), int(cells[f"E{row}"])
            result = demand[(record["month"], check["route"])]
            if sorted([outwards, inwards]) != sorted([int(result["passengers_a_to_b"]), int(result["passengers_b_to_a"])]):
                raise ValueError("City-pair direction values mismatch")
            demand_checks.append({"file": record["filename"], "month": record["month"], "route": check["route"],
                                  "cells": f"D{row},E{row}", "original_total": outwards + inwards,
                                  "reported_total": int(result["passengers_both_directions"]), "passed": True})
    # Reconstruct the major-route examples from the copied source rows, separately
    # from the existing monthly share table.
    raw = read_csv(data / "worked_example_source_rows.csv") + read_csv(data / "regional_schedule_rows.csv")
    extra_codes = {"CHENNAI": "MAA", "SALEM": "SXV", "CUDDAPAH": "CDP", "KADAPA": "CDP"}
    schedule_checks = []
    for month, route, expected in [("2019-11", "MAA-SXV", {"TruJet": 60}),
                                    ("2019-11", "CDP-MAA", {"TruJet": 60}),
                                    ("2023-11", "BOM-DEL", {"Vistara": 951, "Akasa Air": 180}),
                                    ("2026-06", "DEL-PNQ", {"Akasa Air": 120})]:
        first = date.fromisoformat(month + "-01")
        last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
        events = set()
        for r in raw:
            station = r["station_iata"] or extra_codes.get(r["station"].upper(), "")
            current_route = "-".join(sorted((station, r["other_airport"])))
            if current_route != route or r["direction"] != "departure":
                continue
            lo, hi = max(first, date.fromisoformat(r["effective_from"])), min(last, date.fromisoformat(r["effective_to"]))
            flight = r["flight_number"]
            match = re.fullmatch(r"([A-Z0-9]{2})(\d+)([A-Z]?)", flight)
            if match:
                flight = match[1] + str(int(match[2])) + match[3]
            for i in range(max(0, (hi - lo).days + 1)):
                day = lo + timedelta(days=i)
                if str(day.isoweekday()) in r["operating_days"]:
                    events.add((r["airline"], flight, station, r["other_airport"], day))
        counts = Counter(event[0] for event in events)
        total = sum(counts.values())
        for airline, expected_count in expected.items():
            if counts[airline] != expected_count:
                raise ValueError("Worked-example source count mismatch")
            schedule_checks.append({"month": month, "route": route, "airline": airline,
                                    "source_reconstructed_flights": counts[airline], "route_flights": total,
                                    "share_percent": 100 * counts[airline] / total})
        examples = [r for r in read_csv(ROOT / "results/route_evidence/worked_examples.csv") if r["month"] == month and r["route"] == route]
        for example in examples:
            if total != int(example["route_flights"]):
                raise ValueError("Worked route denominator mismatch")
            hhi = sum((100 * n / total) ** 2 for n in counts.values())
            if abs(hhi - float(example["brand_frequency_hhi"])) > 1e-6:
                raise ValueError("Worked route HHI mismatch")
    regional = read_csv(ROOT / "results/route_evidence/regional_route_months.csv")
    shares = read_csv(ROOT / "results/route_evidence/regional_airline_shares.csv")
    by_market = defaultdict(list)
    for r in shares:
        by_market[(r["month"], r["route"])].append(r)
    for r in regional:
        ss = by_market[(r["month"], r["route"])]
        total = sum(int(s["scheduled_flights"]) for s in ss)
        if total != int(r["route_flights"]):
            raise ValueError("Regional sum mismatch")
        hhi = sum((100 * int(s["scheduled_flights"]) / total) ** 2 for s in ss)
        if abs(hhi - float(r["brand_frequency_hhi"])) > 1e-6:
            raise ValueError("Regional HHI mismatch")
    focal = read_csv(ROOT / "results/route_evidence/entrant_route_months.csv")
    if len({(r["month"], r["route"], r["airline"]) for r in focal}) != len(focal):
        raise ValueError("Duplicate focal observation")
    if any(r["airline"] == "TruJet" and r["month"] >= "2022-02" for r in focal):
        raise ValueError("Unexpired TruJet plans treated as continuing service")
    nov = [r for r in shares if r["airline"] == "TruJet" and r["month"] == "2019-11"]
    above_half = sum(int(r["scheduled_flights"]) * 2 >= int(r["route_flights"]) for r in nov)
    if len(nov) != 22 or above_half != 17:
        raise ValueError("H1 count mismatch")
    result = {"passed": True, "original_schedule_pdfs_hashed": len(manifest["documents"]),
              "original_citypair_workbooks_hashed": len(manifest["citypair_workbooks"]),
              "citypair_checks": demand_checks, "worked_schedule_checks": schedule_checks,
              "regional_route_hhi_and_flight_total_checks": len(regional),
              "entrant_route_months": len(focal), "H1": {"covered_routes": len(nov), "at_least_half_share": above_half,
              "percent_of_covered_routes": 100 * above_half / len(nov)},
              "scope": "Source reconstruction and arithmetic verified; schedules remain approved supply and cannot establish complete actual airline passenger shares."}
    (ROOT / "verification/route_verification_results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Route checks passed: {len(manifest['documents'])} schedule PDFs, {len(demand_checks)} original city-pair totals, {len(regional)} HHIs and H1 {above_half}/{len(nov)}.")
    return result


if __name__ == "__main__":
    main()
