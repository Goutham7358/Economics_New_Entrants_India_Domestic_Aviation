"""Check source passages, saved fingerprints, and case-study arithmetic.

Run after calculate.py. Uses supplied text/OCR extracts and standard-library
XML parsing of original DGCA workbooks. PDF rendering/OCR was also inspected
when preparing the case study; this script does not claim to automate that review.
"""

import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal as D
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class SourceHTMLText(HTMLParser):
    """Read visible article text, excluding scripts and site styling."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skipped = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skipped += 1
        if tag in ("p", "br", "li", "h1", "h2", "h3"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skipped = max(0, self.skipped - 1)

    def handle_data(self, data):
        if not self.skipped:
            self.parts.append(data)


def read_original_html(path):
    source = path.read_text()
    reader = SourceHTMLText()
    reader.feed(source)
    # Akasa's saved pages also contain the issuer's article in a Next.js story.
    for script in re.findall(r"<script[^>]*>(.*?)</script>", source, re.S):
        if not script.startswith("{") or '"pageProps"' not in script:
            continue
        try:
            story = json.loads(script)["props"]["pageProps"].get("story", {})
        except (ValueError, KeyError, TypeError):
            continue

        def collect(value):
            if isinstance(value, dict):
                for key in ("body", "content", "text"):
                    if isinstance(value.get(key), str):
                        reader.feed(value[key])
                for item in value.values():
                    if isinstance(item, (dict, list)):
                        collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(story.get("content", {}))
    return re.sub(r"\s+", " ", " ".join(reader.parts)).lower()


def main():
    manifest = json.loads((ROOT / "verification/source_manifest.json").read_text())
    fingerprints = []
    for record in manifest["documents"]:
        path = ROOT / "sources" / record["filename"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record["sha256"]:
            raise ValueError("Changed source: " + path.name)
        fingerprints.append({"file": record["filename"], "sha256_matches": True})
    raw_path = ROOT / "data/carrier_monthly.csv"
    digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    if digest != "30412b650b47b9d8ba50917365b29f120f2da458403533829d65fd11b64c09be":
        raise ValueError("Changed passenger source")
    with raw_path.open() as stream:
        rows = list(csv.DictReader(stream))
    lookup = {(r["airline"], int(r["year"]), int(r["month"])): r
              for r in rows if r["service_type"] == "scheduled_domestic"}
    plan = json.loads((ROOT / "verification/workbook_downloads.json").read_text())
    cells_checked, original_totals = [], {}
    for record in plan:
        path = ROOT / "sources" / record["filename"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["expected_sha256"]:
            raise ValueError("Changed DGCA workbook: " + path.name)
        with zipfile.ZipFile(path) as archive:
            strings = ["".join(s.itertext()) for s in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
            tree = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            cells = {}
            for cell in tree.findall(".//m:c", NS):
                value = cell.find("m:v", NS)
                if value is not None:
                    cells[cell.get("r")] = strings[int(value.text)] if cell.get("t") == "s" else value.text
            for rownum in range(4, 16):
                month = rownum - 3
                name = path.name.lower()
                if name.startswith("vistara"):
                    airline, year, keep = "Vistara", 2017, True
                elif name.startswith("trujet"):
                    airline = "TruJet"
                    year = 2017 if "17" in name else 2018
                    keep = (year == 2017 and month >= 7) or (year == 2018 and month <= 6)
                else:
                    airline = "Akasa Air"
                    year = 2024 if "24" in name else 2025
                    keep = (year == 2024 and month >= 8) or (year == 2025 and month <= 7)
                if not keep:
                    continue
                source_row = lookup[(airline, year, month)]
                total = original_totals.setdefault(airline, {"passengers": D(0), "passenger_km": D(0), "seat_km": D(0)})
                for column, field in [("E", "passengers"), ("F", "passenger_km"), ("G", "seat_km")]:
                    cell = f"{column}{rownum}"
                    original, cleaned = D(cells[cell]), D(source_row[field])
                    difference = abs(original - cleaned)
                    matched = difference == 0 if field == "passengers" else difference <= D("0.000501")
                    if not matched:
                        raise ValueError(f"Workbook mismatch: {path.name}, {cell}")
                    total[field] += original
                    cells_checked.append({"source_file": path.name, "cell": cell, "airline": airline,
                                          "year": year, "month": month, "field": field,
                                          "original_value": str(original), "cleaned_value": str(cleaned),
                                          "absolute_difference": str(difference), "passed": True})
    with (ROOT / "verification/dgca_cell_checks.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(cells_checked[0]))
        writer.writeheader()
        writer.writerows(cells_checked)
    with (ROOT / "results/operating_year_comparisons.csv").open() as stream:
        comparisons = list(csv.DictReader(stream))
    for result in [r for r in comparisons if r["age_year"] == "3"]:
        totals = original_totals[result["airline"]]
        if totals["passengers"] != D(result["airline_passengers"]):
            raise ValueError("Third-year passenger total mismatch")
        plf = 100 * totals["passenger_km"] / totals["seat_km"]
        if abs(plf - D(result["load_factor_percent"])) > D("0.000001"):
            raise ValueError("Third-year load factor mismatch")
    expected = {
        "vistara_icra_2024_08_14.txt": ["12,261.4", "15,310.3", "1,393.3", "581.1", "premium", "10,020"],
        "akasa_icra_2026_06_12.txt": ["4,582.7", "6,167.9", "1,983.5", "2,716.0", "equity infusion", "sale and leaseback"],
        "vistara_merger_rationale_2022_11_29_page3.txt": ["slots", "traffic rights", "resource"],
        "sia_merger_completion_filing_2025_05_15.txt": ["12 November 2024", "25.1%", "20,585 million", "paid in a single tranche"],
        "vistara_sia_call_2024_11_11.txt": ["Is Vistara now profitable", "sale and leasebacks"],
        "cag_udan_audit_2023.txt": ["52(42)", "42 operational routes", "as on March", "2023)"],
        "trujet_nclt_withdrawal_2021_04_29_page1.txt": ["amicably settled", "withdrawn"],
        "trujet_nclt_lease_dispute_2024_05_08.txt": ["dismissed", "disputed", "maintenance"],
        "syllabus.txt": ["Economies of scale", "Break-even analysis", "Oligopoly", "Economic profit vs. accounting profit"],
        "trujet_funding_ownership_2021_10_12.txt": ["October 12, 2021", "Interups is yet to infuse", "transferred", "cash outflow"],
        "trujet_cash_crisis_2022_02_18.txt": ["USD25 million", "financing delays", "single ATR72", "his own panel of management"],
        "akasa_profitability_plan_2025.txt": ["July 22, 2025", "13%", "excluding fuel", "7%", "ancillary", "corporate partners"],
        "akasa_funding_completed_2025_08_19.txt": ["August 19, 2025", "successful completion", "Premji Invest", "360 ONE Asset", "Claypond Capital", "Jhunjhunwala"],
        "akasa_funding_business_standard_2025_08_20.txt": ["$125 million", "people familiar", "estimated"],
        "akasa_ceo_interview_2026_01_07.txt": ["conservative expansion", "well-capitalised", "not yet generating cash from operations"],
        "akasa_management_results_2026_06_23.txt": ["23 June 2026", "10%", "4%", "ancillary", "strategic investment transaction"]
    }
    content_checks = []
    original_html_terms_checked = 0
    for filename, tokens in expected.items():
        content = re.sub(r"\s+", " ", (ROOT / "verification" / filename).read_text()).lower()
        original_path = ROOT / "sources" / Path(filename).with_suffix(".html")
        original_html = read_original_html(original_path) if original_path.exists() else None
        for token in tokens:
            matched = token.lower() in content
            content_checks.append({"file": filename, "search_term": token, "found": matched})
            if not matched:
                raise ValueError(f"Missing source passage: {filename}: {token}")
            if original_html is not None:
                if token.lower() not in original_html:
                    raise ValueError(f"Passage absent from original HTML: {original_path.name}: {token}")
                original_html_terms_checked += 1
    inputs = json.loads((ROOT / "data/financial_inputs.json").read_text())
    financial_checks = []
    for record in inputs["records"]:
        filename = Path(record["source"]).stem + ".txt"
        content = (ROOT / "verification" / filename).read_text()
        for field in ["operating_income", "profit_after_tax"]:
            printed = f"{abs(D(record[field])):,.1f}"
            if printed not in content:
                raise ValueError("Financial input absent from source")
        financial_checks.append({"airline": record["airline"], "year": record["financial_year"], "input_values_found_in_source": True})
    scenarios = list(csv.DictReader((ROOT / "results/break_even_scenarios.csv").open()))
    for row in scenarios:
        incremental_profit = D(row["extra_revenue_to_close_profit_gap_crore"]) * D(row["assumed_incremental_contribution_fraction"])
        if D(row["base_profit_after_tax_crore"]) + incremental_profit != 0:
            raise ValueError("Break-even scenario arithmetic mismatch")
    result = {"verified_on": "2026-10-20", "passed": True,
              "source_fingerprints": fingerprints, "pinned_passenger_csv_matches": True,
              "original_dgca_numeric_cells_checked": len(cells_checked),
              "third_year_airline_months_checked": len(cells_checked) // 3,
              "third_year_passenger_totals_and_load_factors_reconciled": True,
              "content_checks": content_checks, "financial_input_checks": financial_checks,
              "new_html_passage_terms_rechecked_in_originals": original_html_terms_checked,
              "sia_merger_cash_conversion_million_to_crore": str(D("20585") / 10),
              "break_even_arithmetic_checks": len(scenarios),
              "scope": "Five original DGCA workbooks check all three third-year numerators and RPK/ASK inputs. National denominators and first-year values use the pinned DGCA-derived distribution; they were not independently rebuilt from every airline's original workbook. Content searches supplement the recorded visual review and do not establish causation."}
    if (ROOT / "data/routes/regional_schedule_manifest.json").exists():
        import verify_routes
        result["route_evidence"] = verify_routes.main()
    (ROOT / "verification/verification_results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Passed: {len(fingerprints)} source fingerprints, {len(cells_checked)} original DGCA cells, {len(content_checks)} source terms, {len(financial_checks)} financial rows and {len(scenarios)} scenario equations.")


if __name__ == "__main__":
    main()
