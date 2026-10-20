"""Rebuild the saved major-route panel from this repository's schedule archive.

python3 rebuild_routes.py --build uses the saved extracted rows (stdlib only).
python3 rebuild_routes.py --extract rereads all 228 original PDFs with pdftotext.
Adapted from the original project's monthly_route_hhi.py; only local paths,
the July 2026 cutoff and deterministic iteration differ from that algorithm.
"""

from __future__ import annotations

import argparse
import bisect
import calendar
import csv
import hashlib
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "data/routes/full_schedule_archive"
OUT = ROOT / "results/route_input_rebuild"
CUTOFF = date(2026, 7, 31)
NS = {"x": "http://www.w3.org/1999/xhtml"}
CITIES = {
    "DELHI": "DEL", "NEW DELHI": "DEL", "MUMBAI": "BOM",
    "MUMBAI (BOMBAY)": "BOM", "BOMBAY": "BOM", "BANGALORE": "BLR",
    "BENGALURU": "BLR", "KOLKATA": "CCU", "KOLKATA (CALCUTTA)": "CCU",
    "CALCUTTA": "CCU", "HYDERABAD": "HYD", "AHMEDABAD": "AMD",
    "PUNE": "PNQ", "POONA": "PNQ", "CHENNAI": "MAA",
    "CHENNAI(MADRAS)": "MAA", "CHENNAI (MADRAS)": "MAA", "MADRAS": "MAA",
    "SRINAGAR": "SXR", "GUWAHATI": "GAU", "GOA": "GOI", "DABOLIM": "GOI",
}
DATE_RE = re.compile(r"(?:\d{1,2}-[A-Za-z]{3}-\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})")


def csv_write(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not rows and fields is None:
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def parse_date(s):
    m = DATE_RE.search(s)
    s = m[0] if m else s
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%d/%b/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognised date: {s!r}")


def last_sunday(year, month):
    d = date(year, month, calendar.monthrange(year, month)[1])
    return d - timedelta(days=(d.weekday() + 1) % 7)


def season_dates(year, season):
    if season == "summer":
        return last_sunday(year, 3), last_sunday(year, 10) - timedelta(days=1)
    return last_sunday(year, 10), last_sunday(year + 1, 3) - timedelta(days=1)


def airline_from_name(name):
    s = re.sub(r"[^A-Z0-9]", "", unquote(name).rsplit("/", 1)[-1].upper())
    for terms, airline in [
        (("AIRINDIAEXPRESS",), "Air India Express"),
        (("AIRASIA", "AIXCONNECT"), "AirAsia India / AIX Connect"),
        (("ALLIANCE",), "Alliance Air"), (("AIRINDIA",), "Air India"),
        (("INTERGLOBE", "INDIGO"), "IndiGo"), (("VISTARA", "TATASIA"), "Vistara"),
        (("SPICE",), "SpiceJet"), (("GOAIR", "GOFIRST"), "Go First / GoAir"),
        (("TRUJET", "TRUEJET"), "TruJet"),
        (("JETLITE",), "JetLite"), (("JETAIR", "JETSS", "JETW"), "Jet Airways"),
        (("AKASA", "SNV"), "Akasa Air"), (("AIRPEGASUS",), "Air Pegasus"),
        (("AIRCOSTA",), "Air Costa"), (("AIRCARNIVAL",), "Air Carnival"),
        (("STAR", "GHODAWAT"), "Star Air"),
        (("HERITAGE",), "Air Heritage"), (("ODISHA",), "Air Odisha"),
        (("INDIAONE", "GSECMONARCH"), "IndiaOne Air"),
        (("DECCAN",), "Air Deccan"), (("ZOOM",), "Zoom Air"),
        (("PAWAN",), "Pawan Hans"), (("JUSTUDO",), "FLY91"), (("FLYBIG",), "FlyBig"),
    ]:
        if any(t in s for t in terms):
            return airline
    return "UNKNOWN"


def source_inventory():
    """Read saved publications; never download or depend on another project."""
    for original in json.loads((ARCHIVE / "source_manifest.json").read_text()):
        item = dict(original)
        path = ROOT / item["path"]
        payload = path.read_bytes()
        if not payload.startswith(b"%PDF") or hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise ValueError("Original schedule changed: " + path.name)
        yield item


def get_lines(page):
    words = sorted(page.findall(".//x:word", NS), key=lambda w: (float(w.get("yMin")), float(w.get("xMin"))))
    lines = []
    for w in words:
        y = float(w.get("yMin"))
        if not lines or abs(y - lines[-1][0]) > 1.8:
            lines.append((y, []))
        lines[-1][1].append(w)
    return [(y, sorted(ws, key=lambda w: float(w.get("xMin")))) for y, ws in lines]


def center(w):
    return (float(w.get("xMin")) + float(w.get("xMax"))) / 2


def header_centers(page):
    words = page.findall(".//x:word", NS)
    freq = next((w for w in words if w.text == "Frequency"), None)
    if freq is None:
        return None
    fy = float(freq.get("yMin"))
    nearby = [w for w in words if abs(float(w.get("yMin")) - fy) < 23]
    def match(token):
        return sorted([w for w in nearby if (w.text or "").rstrip(".").lower() == token.lower()], key=center)
    left = []
    for token in ["Sl", "Flight", "Operator", "Aircraft"]:
        ws = match(token)
        if token == "Sl" and not ws:
            ws = [w for w in nearby if (w.text or "").lower().startswith("sl.")]
        if not ws:
            return None
        left.append(center(ws[0]))
    right = []
    for token in ["Arrival", "Departure", "Effective"]:
        ws = match(token)
        if token == "Departure":
            ws = sorted([w for w in nearby if (w.text or "").startswith("Departur")], key=center)
        if len(ws) != 2:
            return None
        right.extend(center(w) for w in ws)
    centers = left + [center(freq)] + right
    return centers


def pdf_extract(item):
    path = ROOT / item["path"]
    with tempfile.TemporaryDirectory(prefix="route-monthly-") as tmp:
        bbox = Path(tmp) / "words.html"
        subprocess.run(["pdftotext", "-bbox-layout", str(path), str(bbox)], check=True, capture_output=True)
        pages = ET.parse(bbox).getroot().findall(".//x:page", NS)
    first_text = " ".join(w.text or "" for w in pages[0].findall(".//x:word", NS))
    item["pages"] = len(pages)
    item["airline"] = airline_from_name(item["original_url"])
    season = "winter" if "WINTER" in first_text.upper() else "summer"
    # Some reports have a stale SUMMER caption in an October winter filing.
    # The seasonal filename and the dated rows identify the intended season.
    source_name = unquote(item["original_url"]).rsplit("/", 1)[-1]
    if re.search(r"(?:ws|_w)\d{2,4}", source_name, re.I):
        season = "winter"
    found_years = [int(x) for x in re.findall(r"\b(20\d{2})\b", first_text)]
    if found_years:
        year = found_years[0]
    else:
        name = item["filename"]
        m = re.search(r"(?:ss|ws|_w)(\d{2})(?:\D|$)", name, re.I)
        if not m:
            item.update(parse_status="no readable year", season="", source_rows=0)
            return [], [], item
        year = 2000 + int(m[1])
    lo, hi = season_dates(year, season)
    item.update(year=year, season=season, season_start=lo.isoformat(), season_end=hi.isoformat())
    movement = "MOVEMENT" in first_text.upper() and "REPORT" in first_text.upper()
    if not movement:
        item.update(parse_status="legacy table: requires separate extraction", source_rows=0)
        return [], [], item
    station = None
    records, errors = [], []
    last_centers = None
    for pageno, page in enumerate(pages, 1):
        width = float(page.get("width"))
        if width > 800:
            centers = [57 + 64.2 * (i + .5) for i in range(11)]
        else:
            centers = header_centers(page) or last_centers
        if centers is None:
            errors.append({"file": path.name, "page": pageno, "station": station, "problem": "unrecognised columns", "text": ""})
            continue
        last_centers = centers
        physical = sorted((x, i) for i, x in enumerate(centers))
        bounds = [(a[0] + b[0]) / 2 for a, b in zip(physical, physical[1:])]
        headfreq = next((float(w.get("yMin")) for w in page.findall(".//x:word", NS) if w.text == "Frequency"), 0)
        for y, words in get_lines(page):
            if y <= headfreq + 8:
                continue
            text = " ".join(w.text or "" for w in words)
            cells = [[] for _ in range(11)]
            for w in words:
                cells[physical[bisect.bisect_right(bounds, center(w))][1]].append(w.text or "")
            cells = [" ".join(c) for c in cells]
            if not re.fullmatch(r"\d+", cells[0]):
                if DATE_RE.search(text) or not re.fullmatch(r"[A-Za-z][A-Za-z /().-]*", text):
                    continue
                if re.search(r"\b(approved|schedule|operator|arrival|departure|frequency|director|report|effective)\b", text, re.I):
                    continue
                mid = (min(float(w.get("xMin")) for w in words) + max(float(w.get("xMax")) for w in words)) / 2
                if (text.upper() in CITIES or abs(mid - (centers[0] + centers[-1]) / 2) < 20
                        or abs(mid - width / 2) < 30):
                    station = text.strip()
                continue
            if not re.search(r"\d", cells[1]):
                continue
            try:
                if station is None:
                    raise ValueError("missing station")
                freq = cells[4].replace(" ", "")
                freq = "1234567" if freq.lower() == "daily" else freq
                if not re.fullmatch(r"[1-7]+", freq):
                    raise ValueError("invalid frequency")
                begin, end = parse_date(cells[9]), parse_date(cells[10])
                if begin > end:
                    raise ValueError("reversed validity")
                if bool(cells[5]) == bool(cells[7]):
                    raise ValueError("ambiguous movement direction")
                direction = "arrival" if cells[5] else "departure"
                endpoint = cells[5] if cells[5] else cells[7]
                tm = cells[6] if cells[5] else cells[8]
                if not re.fullmatch(r"[A-Z]{3}", endpoint):
                    raise ValueError("invalid endpoint")
                # Time is retained for audit but is not an input to frequency HHI.
                # A few originals print Excel time fractions or omit a time.
                if re.fullmatch(r"\d{1,2}:\d\d", tm):
                    tm = tm.zfill(5)
                flight = re.match(r"([A-Z0-9]{2})\s*(\d+[A-Z]?)", cells[1])
                if not flight:
                    raise ValueError("unrecognised flight number")
                records.append({"source_file": path.name, "source_page": pageno,
                                "source_row": cells[0], "station": station,
                                "station_iata": CITIES.get(station.upper(), ""),
                                "airline": item["airline"], "flight_number": "".join(flight.groups()),
                                "operator_code": cells[2], "operating_days": "".join(sorted(set(freq))),
                                "direction": direction, "other_airport": endpoint,
                                "scheduled_time": tm, "effective_from": begin.isoformat(),
                                "effective_to": end.isoformat(), "season_year": year,
                                "season": season, "source_url": item["source_url"]})
            except ValueError as exc:
                errors.append({"file": path.name, "page": pageno, "station": station,
                               "problem": str(exc), "text": text, "cells": " | ".join(cells)})
    item.update(parse_status="extracted" if not errors else "extracted with issues", source_rows=len(records), extraction_issues=len(errors))
    return records, errors, item


def extract_all():
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    records, errors, inventory = [], [], []
    for number, item in enumerate(source_inventory(), 1):
        rr, ee, item = pdf_extract(item)
        records.extend(rr)
        errors.extend(ee)
        inventory.append(item)
        if number % 25 == 0:
            print(f"Read {number} original schedule PDFs", flush=True)
    csv_write(ARCHIVE / "source_schedule_rows.csv", records)
    csv_write(ARCHIVE / "extraction_issues.csv", errors, ["file", "page", "station", "problem", "text", "cells"])
    (ARCHIVE / "source_manifest.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print("PDFs", len(inventory), "rows", len(records), "issues", len(errors))
    print("Issues at selected airports", sum(CITIES.get((r.get("station") or "").upper(), "") != "" for r in errors))
    print("Statuses", Counter(x["parse_status"] for x in inventory))


def top_routes():
    traffic = ROOT / "data/routes/domestic_route_monthly.csv"
    totals = Counter()
    months = set()
    for r in csv.DictReader(traffic.open()):
        if r["year"] == "2025":
            totals[tuple(sorted((r["origin"], r["destination"])))] += int(float(r["passengers"]))
            months.add(r["month"])
    assert len(months) == 12
    rows = [{"rank_2025": i, "route": "-".join(pair), "airport_a": pair[0],
             "airport_b": pair[1], "passengers_2025_both_directions": n}
            for i, (pair, n) in enumerate(totals.most_common(20), 1)]
    csv_write(OUT / "top20_routes.csv", rows)
    return rows


def coverage_reason(day, route):
    if day >= date(2026, 10, 1):
        return "calendar month not yet completed at retrieval"
    if day < date(2019, 3, 31):
        return "complete historical season not available"
    if date(2020, 3, 1) <= day <= date(2020, 10, 31):
        return "pandemic suspension/restart: original season plan not usable"
    if date(2022, 8, 1) <= day <= date(2022, 10, 29):
        return "initial Akasa season filing unavailable"
    if date(2024, 3, 31) <= day <= date(2024, 10, 26):
        return "complete Summer 2024 filings unavailable"
    if route == "HYD-MAA" and date(2021, 3, 28) <= day <= date(2021, 10, 30):
        return "TruJet Summer 2021 filing unavailable"
    if route == "BLR-HYD" and date(2021, 3, 28) <= day <= date(2021, 10, 30):
        return "Star Air Summer 2021 omits Hyderabad departure table"
    # Removed automatically if the missing original is recovered.
    if route == "BLR-HYD" and date(2022, 10, 30) <= day <= date(2023, 3, 25):
        files = [x for x in json.loads((ARCHIVE / "source_manifest.json").read_text())
                 if x.get("year") == 2022 and x.get("season") == "winter" and x.get("airline") == "Star Air"]
        if not files:
            return "Star Air Winter 2022 filing unavailable"
    return ""


def brand_at_date(airline, flight, day):
    """Apply documented cessation dates and the published UK-to-AI conversion."""
    if airline in {"Jet Airways", "JetLite"} and day > date(2019, 4, 17):
        return None
    if airline == "Go First / GoAir" and day >= date(2023, 5, 3):
        return None
    if airline == "Vistara" and day >= date(2024, 11, 12):
        number = str(int(re.sub(r"^UK", "", flight)))
        return "Air India", "AI2" + number.zfill(3)
    return airline, flight


def group_name(airline, month):
    """Same conservative grouping convention as the national project panel."""
    if airline in {"Jet Airways", "JetLite"}:
        return "Jet Airways Group"
    if airline in {"Air India", "Air India Express"}:
        return "Air India Group"
    if month >= date(2022, 1, 1) and airline in {"Vistara", "AirAsia India / AIX Connect"}:
        return "Air India Group"
    return airline


def build_monthly():
    routes = top_routes()
    route_info = {r["route"]: r for r in routes}
    records = list(csv.DictReader((ARCHIVE / "source_schedule_rows.csv").open()))
    inventory = json.loads((ARCHIVE / "source_manifest.json").read_text())
    inv = {r["filename"]: r for r in inventory}
    relevant = []
    for r in records:
        if not r["station_iata"]:
            continue
        route = "-".join(sorted((r["station_iata"], r["other_airport"])))
        if route not in route_info:
            continue
        r = dict(r)
        r["route"] = route
        r["lo"] = max(date.fromisoformat(r["effective_from"]), date.fromisoformat(inv[r["source_file"]]["season_start"]))
        r["hi"] = min(date.fromisoformat(r["effective_to"]), date.fromisoformat(inv[r["source_file"]]["season_end"]))
        relevant.append(r)
    # Every unresolved extraction issue on a selected route must be reviewed.
    problems = []
    for r in csv.DictReader((ARCHIVE / "extraction_issues.csv").open()):
        item = inv[r["file"]]
        if item.get("year", 0) < 2019:
            continue
        station = CITIES.get((r.get("station") or "").upper(), "")
        if not station:
            continue
        endpoints = set(re.findall(r"\b[A-Z]{3}\b", r["text"]))
        for endpoint in endpoints:
            route = "-".join(sorted((station, endpoint)))
            if route in route_info:
                problems.append({**r, "route": route})
    assert not problems, f"Unresolved extraction issues on selected routes: {problems}"
    outputs, shares, coverage, daily = [], [], [], []
    used = set()
    duplicate_days = 0
    for year in range(2015, 2027):
        for month in range(1, 13):
            start = date(year, month, 1)
            if start > CUTOFF:
                continue
            end = date(year, month, calendar.monthrange(year, month)[1])
            monthstr = start.strftime("%Y-%m")
            good = set()
            for route in route_info:
                reasons = {coverage_reason(start + timedelta(days=i), route) for i in range(end.day)} - {""}
                coverage.append({"month": monthstr, "route": route, "rank_2025": route_info[route]["rank_2025"],
                                 "full_month_source_coverage": not reasons, "reason": "; ".join(sorted(reasons))})
                if not reasons:
                    good.add(route)
            if not good:
                continue
            events = {"departure": set(), "arrival": set()}
            refs = {"departure": defaultdict(set), "arrival": defaultdict(set)}
            for r in relevant:
                if r["route"] not in good or r["hi"] < start or r["lo"] > end:
                    continue
                lo, hi = max(r["lo"], start), min(r["hi"], end)
                if r["direction"] == "departure":
                    origin, dest = r["station_iata"], r["other_airport"]
                else:
                    origin, dest = r["other_airport"], r["station_iata"]
                for i in range((hi - lo).days + 1):
                    day = lo + timedelta(days=i)
                    if str(day.isoweekday()) not in r["operating_days"]:
                        continue
                    brand = brand_at_date(r["airline"], r["flight_number"], day)
                    if brand is None:
                        continue
                    airline, flight = brand
                    # Remove insignificant leading zeros from flight identity.
                    fm = re.fullmatch(r"([A-Z0-9]{2})(\d+)([A-Z]?)", flight)
                    if fm:
                        flight = fm[1] + str(int(fm[2])) + fm[3]
                    key = (r["route"], airline, flight, origin, dest, day.isoformat())
                    if key in events[r["direction"]] and r["direction"] == "departure":
                        duplicate_days += 1
                    events[r["direction"]].add(key)
                    refs[r["direction"]][r["route"]].add(r["source_file"])
                    used.add((r["source_file"], r["source_page"], r["source_row"], r["station"], r["direction"]))
            counts = {direction: defaultdict(Counter) for direction in events}
            dirs = defaultdict(Counter)
            daycounts = Counter()
            for direction, evs in events.items():
                for route, airline, flight, origin, dest, day in sorted(evs):
                    counts[direction][route][airline] += 1
                    if direction == "departure":
                        dirs[(route, airline)][origin] += 1
                        daycounts[(day, route, origin, dest, airline)] += 1
            for (day, route, origin, dest, airline), n in sorted(daycounts.items()):
                daily.append({"date": day, "route": route, "origin": origin, "destination": dest,
                              "airline": airline, "scheduled_departures": n})
            for route in sorted(good, key=lambda k: route_info[k]["rank_2025"]):
                brandcounts = counts["departure"][route]
                if not brandcounts:
                    raise ValueError(f"No departures for covered route-month {route} {monthstr}")
                total = sum(brandcounts.values())
                grouped = Counter()
                for airline, n in brandcounts.items():
                    group = group_name(airline, start)
                    grouped[group] += n
                    shares.append({"month": monthstr, "route": route, "airline": airline, "group": group,
                                   "flights_a_to_b": dirs[(route, airline)][route_info[route]["airport_a"]],
                                   "flights_b_to_a": dirs[(route, airline)][route_info[route]["airport_b"]],
                                   "scheduled_flights": n, "route_flights": total,
                                   "frequency_share_pct": round(100 * n / total, 10),
                                   "brand_hhi_contribution": round(10000 * (n / total) ** 2, 10)})
                group_ranks = sorted(grouped.items(), key=lambda p: (-p[1], p[0]))
                counterpart = counts["arrival"][route]
                agrees = brandcounts == counterpart
                outputs.append({"month": monthstr, "route": route, "rank_2025": route_info[route]["rank_2025"],
                                "airport_a": route_info[route]["airport_a"], "airport_b": route_info[route]["airport_b"],
                                "scheduled_flights_both_directions": total,
                                "flights_a_to_b": sum(dirs[(route, a)][route_info[route]["airport_a"]] for a in brandcounts),
                                "flights_b_to_a": sum(dirs[(route, a)][route_info[route]["airport_b"]] for a in brandcounts),
                                "airline_count": len(brandcounts), "group_count": len(grouped),
                                "brand_frequency_hhi": round(10000 * sum((n / total) ** 2 for n in brandcounts.values()), 8),
                                "group_frequency_hhi": round(10000 * sum((n / total) ** 2 for n in grouped.values()), 8),
                                "group_cr2_pct": round(100 * sum(n for _, n in group_ranks[:2]) / total, 8),
                                "largest_group": group_ranks[0][0],
                                "counterpart_count_agreement": agrees,
                                "counterpart_absolute_count_difference": sum(abs(brandcounts[a] - counterpart[a]) for a in set(brandcounts) | set(counterpart)),
                                "source_pdf_count": len(refs["departure"][route]),
                                "basis": "approved nonstop departure frequency; both directions; cessation/merger adjusted"})
    all_outputs, all_shares = outputs, shares
    # This is an explicitly disclosed source-quality screen, not a claim that
    # scheduled flights were actually operated. Compare counts by airline so
    # positive and negative differences cannot cancel across competitors.
    for r in all_outputs:
        r["counterpart_count_difference_pct"] = round(100 * r["counterpart_absolute_count_difference"] / r["scheduled_flights_both_directions"], 8)
    within_tolerance = [r for r in all_outputs if r["counterpart_count_difference_pct"] <= 5]
    per_month = Counter(r["month"] for r in within_tolerance)
    outputs = [r for r in within_tolerance if per_month[r["month"]] >= 10]
    selected_keys = {(r["month"], r["route"]) for r in outputs}
    shares = [r for r in shares if (r["month"], r["route"]) in selected_keys]
    daily = [r for r in daily if (r["date"][:7], r["route"]) in selected_keys]
    results_by_key = {(r["month"], r["route"]): r for r in all_outputs}
    for r in coverage:
        key = (r["month"], r["route"])
        r["included_in_main_csv"] = key in selected_keys
        if r["full_month_source_coverage"] and key not in selected_keys:
            result = results_by_key[key]
            r["reason"] = ("airline endpoint-count difference exceeds 5 percent" if result["counterpart_count_difference_pct"] > 5
                           else "fewer than ten routes pass the monthly source-quality screen")
    csv_write(OUT / "audit/published_departure_hhi_before_quality_screen.csv", all_outputs)
    csv_write(OUT / "audit/carrier_shares_before_quality_screen.csv", all_shares)
    csv_write(OUT / "monthly_route_hhi.csv", outputs)
    csv_write(OUT / "monthly_carrier_route_shares.csv", shares)
    csv_write(OUT / "monthly_coverage.csv", coverage)
    csv_write(OUT / "daily_airline_route_counts.csv", daily)
    csv_write(OUT / "monthly_route_hhi_matching_counts.csv", [r for r in outputs if r["counterpart_count_agreement"]])
    months_by_route = defaultdict(list)
    for monthstr, route in selected_keys:
        ms = date.fromisoformat(monthstr + "-01")
        months_by_route[route].append((ms, date(ms.year, ms.month, calendar.monthrange(ms.year, ms.month)[1])))
    source_rows = []
    for r in records:
        if (r["source_file"], r["source_page"], r["source_row"], r["station"], r["direction"]) not in used:
            continue
        route = "-".join(sorted((r["station_iata"], r["other_airport"])))
        if any(date.fromisoformat(r["effective_from"]) <= me and date.fromisoformat(r["effective_to"]) >= ms
               for ms, me in months_by_route[route]):
            source_rows.append(r)
    csv_write(OUT / "source_rows_used.csv", source_rows)
    used_files = {r["source_file"] for r in source_rows}
    csv_write(OUT / "source_files_used.csv", [{k: r.get(k, "") for k in ["filename", "path", "airline", "year", "season", "season_start", "season_end", "pages", "sha256", "bytes", "source_url"]} for r in inventory if r["filename"] in used_files])
    # Reconcile both directions and every airline's shares against the final HHI.
    grouped_shares = defaultdict(list)
    for r in shares:
        grouped_shares[(r["month"], r["route"])].append(r)
    assert len({(r["month"], r["route"]) for r in outputs}) == len(outputs)
    for r in outputs:
        ss = grouped_shares[(r["month"], r["route"])]
        assert sum(s["scheduled_flights"] for s in ss) == r["scheduled_flights_both_directions"]
        assert r["flights_a_to_b"] + r["flights_b_to_a"] == r["scheduled_flights_both_directions"]
        assert r["flights_a_to_b"] > 0 and r["flights_b_to_a"] > 0
        assert abs(sum(s["frequency_share_pct"] for s in ss) - 100) < 1e-7
        assert abs(sum(s["brand_hhi_contribution"] for s in ss) - r["brand_frequency_hhi"]) < 1e-6
        assert 0 < r["brand_frequency_hhi"] <= r["group_frequency_hhi"] <= 10000
    meta = {"retrieved_on": "2026-10-19", "route_months": len(outputs), "routes": len({r["route"] for r in outputs}),
            "months": len({r["month"] for r in outputs}), "first_month": min(r["month"] for r in outputs),
            "last_month": max(r["month"] for r in outputs), "used_original_pdfs": len(used_files),
            "used_extracted_rows": len(source_rows), "dated_departures": sum(r["scheduled_flights_both_directions"] for r in outputs),
            "duplicate_source_flight_days_collapsed_before_quality_screen": duplicate_days,
            "matching_counterpart_route_months": sum(r["counterpart_count_agreement"] for r in outputs),
            "all_20_routes_months": sum(n == 20 for n in Counter(r["month"] for r in outputs).values()),
            "minimum_routes_per_month": min(Counter(r["month"] for r in outputs).values()),
            "maximum_routes_per_month": max(Counter(r["month"] for r in outputs).values()),
            "source_quality_rule": "Sum of absolute airline endpoint count differences / departure count <= 5%; at least 10 routes retained per month",
            "route_months_before_quality_screen": len(all_outputs),
            "months_before_quality_screen": len({r["month"] for r in all_outputs}),
            "checks_passed": ["source SHA256 recorded", "zero unresolved extraction issues on selected routes",
                              "full calendar month coverage", "both directions present", "unique flight-date-leg identities",
                              "airline shares sum to 100", "monthly flight totals reconcile", "HHI recomputed from shares",
                              "0 < brand HHI <= group HHI <= 10000"],
            "counterpart_audit": "Airline monthly arrival counts at destination compared with departures at origin. Disagreements retained and flagged; arrival rows do not enter HHI."}
    (OUT / "verification.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Major-route rebuild: {len(outputs)} route-months; {len(used_files)} source PDFs; through {CUTOFF:%Y-%m}.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--build", action="store_true")
    args = ap.parse_args()
    if args.extract:
        extract_all()
    if args.build:
        build_monthly()
