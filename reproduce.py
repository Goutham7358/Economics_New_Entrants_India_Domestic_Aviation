"""Rebuild and verify the study offline from files in this repository."""

import argparse
import shutil

import calculate
import rebuild_routes
import verify
import verify_reproduction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-pdfs", action="store_true",
        help="Re-extract the 228 saved schedule PDFs first; requires pdftotext (Poppler).",
    )
    args = parser.parse_args()
    verify_reproduction.verify_inputs()
    if args.from_pdfs:
        if shutil.which("pdftotext") is None:
            parser.error("--from-pdfs requires Poppler's pdftotext on PATH")
        rebuild_routes.extract_all()
        verify_reproduction.verify_inputs()
    calculate.main()
    verify.main()
    verify_reproduction.main()
    print("Reproduction complete. All checks passed; results are in results/.")


if __name__ == "__main__":
    main()
