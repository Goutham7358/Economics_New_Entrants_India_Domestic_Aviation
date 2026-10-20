"""Check offline inputs, rebuilt route tables and headline case-study figures."""

import csv
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent


def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def verify_inputs():
    manifest = json.loads((ROOT / "verification/reproduction_inputs.json").read_text())
    for record in manifest["files"]:
        path = ROOT / record["path"]
        if not path.resolve().is_relative_to(ROOT) or path.is_symlink():
            raise ValueError("Input is outside this repository: " + str(path))
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Input fingerprint changed: " + record["path"])
    return len(manifest["files"])


def compare_table(snapshot, rebuilt, keys):
    def keyed(path):
        result = {}
        for row in rows(path):
            key = tuple(row[k] for k in keys)
            if key in result:
                raise ValueError("Duplicate table key: " + str(path))
            result[key] = row
        return result
    saved, calculated = keyed(snapshot), keyed(rebuilt)
    if saved.keys() != calculated.keys():
        raise ValueError("Rebuilt table has different keys: " + snapshot.name)
    compared = 0
    for key, record in saved.items():
        for field, value in record.items():
            other = calculated[key].get(field)
            if value != other:
                try:
                    close = abs(Decimal(value) - Decimal(other)) <= Decimal("0.00000002")
                except (InvalidOperation, TypeError):
                    close = False
                if not close:
                    raise ValueError(f"Rebuild differs: {snapshot.name}, {key}, {field}: {value} != {other}")
            compared += 1
    return {"snapshot": snapshot.name, "rows": len(saved), "cells_compared": compared,
            "passed": True, "numeric_tolerance": "0.00000002"}


def main():
    checked_inputs = verify_inputs()
    data = ROOT / "data/routes"
    rebuilt = ROOT / "results/route_input_rebuild"
    tables = [
        compare_table(data / "top20_routes.csv", rebuilt / "top20_routes.csv", ["route"]),
        compare_table(data / "top20_monthly_route_hhi.csv", rebuilt / "monthly_route_hhi.csv", ["month", "route"]),
        compare_table(data / "top20_monthly_airline_shares.csv", rebuilt / "monthly_carrier_route_shares.csv", ["month", "route", "airline"]),
        compare_table(data / "top20_monthly_coverage.csv", rebuilt / "monthly_coverage.csv", ["month", "route"]),
    ]
    archive = json.loads((data / "full_schedule_archive/source_manifest.json").read_text())
    for record in archive:
        if hashlib.sha256((ROOT / record["path"]).read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Changed original PDF: " + record["filename"])
    full = rows(data / "full_schedule_archive/source_schedule_rows.csv")
    fields = list(full[0])
    identities = {tuple(r[f] for f in fields) for r in full}
    subset_checks = []
    for filename in ["regional_schedule_rows.csv", "top20_source_rows.csv", "worked_example_source_rows.csv"]:
        subset = rows(data / filename)
        if any(tuple(r[f] for f in fields) not in identities for r in subset):
            raise ValueError("Source row not present in full extraction: " + filename)
        subset_checks.append({"file": filename, "rows": len(subset), "all_present_in_full_extraction": True})
    links = 0
    for filename in ["README.md", "CASE_STUDY.md", "ACTIONS_AND_FUNDING.md", "ROUTE_DATA.md", "THIRD_PARTY_SOURCES.md", "verification/SOURCE_CHECKS.md"]:
        path = ROOT / filename
        for link in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if link.startswith(("https:", "http:", "mailto:", "#")):
                continue
            destination = (path.parent / unquote(link.split("#")[0])).resolve()
            if not destination.is_relative_to(ROOT) or not destination.exists():
                raise ValueError(f"Nonportable or missing link: {filename}: {link}")
            links += 1
    report = (ROOT / "CASE_STUDY.md").read_text().replace("−", "-")
    claims = []

    def claim(label, text):
        if text not in report:
            raise ValueError(f"Headline figure absent from case study: {label}: {text}")
        claims.append({"claim": label, "calculated_display": text, "present_in_case_study": True})

    result = json.loads((ROOT / "results/calculations.json").read_text())
    for record in result["financial_changes"]:
        claim(record["airline"] + " revenue growth", f"{record['operating_income_growth_percent']:.2f}%")
        claim(record["airline"] + " loss change", f"{record['net_loss_magnitude_change_percent']:+.2f}%")
        claim(record["airline"] + " net margin change", f"{abs(record['net_margin_change_percentage_points']):.2f}")
    for record in result["financial_years"]:
        claim(record["airline"] + " net margin", f"{record['net_profit_margin_percent']:.2f}%")
    for record in rows(ROOT / "results/route_evidence/worked_examples.csv"):
        claim(record["airline"] + " route share " + record["route"], f"{float(record['frequency_share_pct']):.2f}%")
        claim(record["route"] + " HHI", f"{float(record['brand_frequency_hhi']):,.2f}")
    hypothesis = result["hypotheses"][0]
    numerator = hypothesis["routes_with_trujet_share_at_least_50_percent"]
    denominator = hypothesis["routes_passing_screen"]
    claim("H1 route counts", f"{numerator} of {denominator}")
    claim("H1 percentage", f"{100 * numerator / denominator:.2f}%")
    for record in result["airline_summary"]:
        claim(record["airline"] + " positive months", str(record["positive_passenger_months"]))
    independent_financial_checks = []
    for record in result["financial_changes"]:
        earlier, later = sorted([r for r in result["financial_years"] if r["airline"] == record["airline"]], key=lambda r: r["financial_year"])
        growth = 100 * (float(later["operating_income"]) / float(earlier["operating_income"]) - 1)
        if abs(growth - record["operating_income_growth_percent"]) > 1e-9:
            raise ValueError("Independent financial growth calculation differs")
        margin_delta = 100 * (float(later["profit_after_tax"]) / float(later["operating_income"]) - float(earlier["profit_after_tax"]) / float(earlier["operating_income"]))
        if abs(margin_delta - record["net_margin_change_percentage_points"]) > 1e-9:
            raise ValueError("Independent financial margin calculation differs")
        independent_financial_checks.append({"airline": record["airline"], "growth_and_margin_recomputed": True})
    summary = {"passed": True, "offline_input_files_hashed": checked_inputs,
               "original_schedule_pdfs_hashed": len(archive), "major_route_rebuild": tables,
               "source_row_subsets": subset_checks, "local_document_links_checked": links,
               "case_study_claims": claims, "independent_financial_checks": independent_financial_checks,
               "scope": "Numerical results and documented inputs are reproducible. Strategic interpretations remain evidence-based arguments, not causal estimates."}
    (ROOT / "verification/reproduction_results.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Offline checks passed: {checked_inputs} input files, {len(archive)} original schedule PDFs, {len(claims)} headline figures and {links} local document links.")
    return summary


if __name__ == "__main__":
    main()
