"""
Classify duplicated cik-report_year groups in the 10-K sample.

Input:
data/generated/tone/initial_10k_sample_2002_2024.csv

Output:
data/generated/tone/duplicate_cik_report_year_classification.csv

This script identifies company-year groups with more than one 10-K observation,
summarizes each duplicate group, and assigns a rule-based reason_guess and
reason_type for later deduplication.

The output is used by:
code/tone/05_build_dedup_full_sample.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# -----------------------------
# Path settings
# -----------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]

TONE_DIR = PROJECT_ROOT / "data" / "generated" / "tone"

INPUT_CSV = TONE_DIR / "initial_10k_sample_2002_2024.csv"
OUTPUT_CSV = TONE_DIR / "duplicate_cik_report_year_classification.csv"


# -----------------------------
# Classification labels
# -----------------------------
REASON_LABELS = {
    1: "A. different report_date: likely fiscal-year change / transition report",
    2: "B. same report_date: multiple series / asset-pool / trust filings",
    3: "C. same report_date + same word_count: likely duplicate / amendment / re-file",
    4: "D. filename suggests non-10-K or placeholder was captured",
    5: "E. same report_date + different text: manual check needed",
}


def normalize_cik(value: object) -> str:
    """Normalize CIK to a 10-digit string."""
    if pd.isna(value):
        return ""
    digits = re.sub(r"\D", "", str(value))
    if digits == "":
        return ""
    return digits.zfill(10)


def first_nonmissing(series: pd.Series) -> object:
    """Return the first non-missing, non-blank value in a series."""
    for value in series:
        if pd.isna(value):
            continue
        text = str(value).strip()
        if text != "":
            return value
    return pd.NA


def filename_from_url(url_value: object) -> str:
    """Extract the final filename from a SEC URL."""
    if pd.isna(url_value) or str(url_value).strip() == "":
        return ""

    parsed = urlparse(str(url_value).strip())
    filename = Path(unquote(parsed.path)).name
    return filename


def join_unique_text(values: pd.Series, separator: str = "|") -> str:
    """
    Join non-missing values into one string.

    This keeps row order and keeps duplicates, because duplicate filenames such
    as d10k.htm can occur in different SEC accession folders.
    """
    cleaned = []
    for value in values:
        if pd.isna(value):
            continue
        text = str(value).strip()
        if text:
            cleaned.append(text)
    return separator.join(cleaned)


def join_urls(values: pd.Series) -> str:
    """
    Join URL examples into one string.

    The existing duplicated file uses ' | ' between URLs, so this function uses
    that separator.
    """
    cleaned = []
    for value in values:
        if pd.isna(value):
            continue
        text = str(value).strip()
        if text:
            cleaned.append(text)
    return " | ".join(cleaned)


def securitization_fund_like_name(name_value: object) -> bool:
    """
    Flag names that look like securitization, trust, asset-pool, or fund filings.

    This is a heuristic. It is designed to identify cases where the same legal
    filer may file many 10-Ks for different pools, series, or trusts in the same
    report year.
    """
    if pd.isna(name_value):
        return False

    name = str(name_value).upper()

    patterns = [
        r"\bTRUST\b",
        r"\bTR\b",
        r"\bSERIES\b",
        r"\bRECEIVABLES?\b",
        r"\bASSET\b",
        r"\bASSET[- ]BACKED\b",
        r"\bMORTGAGE\b",
        r"\bSECURIT",
        r"\bPASS[- ]THROUGH\b",
        r"\bAUTO\b",
        r"\bLOAN\b",
        r"\bLEASE\b",
        r"\bBANK\b",
        r"\bCREDIT\b",
        r"\bMASTER\b",
        r"\bOWNER\b",
        r"\bCERTIFICATE\b",
        r"\bCERTIFICATES\b",
        r"\bPOOL\b",
        r"\bFUND\b",
        r"\bFUNDING\b",
        r"\bDEPOSITOR\b",
        r"\bSPV\b",
        r"\bLLC\b.*\bTRUST\b",
    ]

    return any(re.search(pattern, name) for pattern in patterns)


def any_non10k_like_filename(filenames: list[str]) -> bool:
    """
    Flag filenames that look like non-10-K, late notice, Form 10, or paper placeholders.

    This is intentionally conservative and based on filename text only.
    """
    for filename in filenames:
        lower = filename.lower().strip()

        if lower == "":
            continue

        if lower.endswith(".paper"):
            return True

        # NT 10-K / late filing notice, not the actual 10-K.
        if re.search(r"(^|[_\-/])nt[-_]?10[-_]?k", lower):
            return True

        if "nt10k" in lower or "nt_10k" in lower or "nt-10k" in lower:
            return True

        if lower in {"late.htm", "late.html", "late.txt"}:
            return True

        # Form 10 is not Form 10-K.
        if re.search(r"(^|[_\-/])form[_-]?10(\.|_|-)", lower):
            return True

    return False


def any_amend_like_filename(filenames: list[str]) -> bool:
    """Flag filenames that look like amendments."""
    for filename in filenames:
        lower = filename.lower().strip()

        if re.search(r"10[-_]?k[-_]?a", lower):
            return True

        if "amend" in lower or "amended" in lower:
            return True

    return False


def any_paper_placeholder(filenames: list[str]) -> bool:
    """Flag SEC paper placeholder files."""
    return any(filename.lower().strip().endswith(".paper") for filename in filenames)


def classify_reason(row: pd.Series) -> tuple[str, int]:
    """
    Assign reason_guess and reason_type.

    The rule order matters:

    1. Different report_date:
       likely fiscal-year change or transition report.
       Keep for this round.

    2. Same report_date + securitization/fund-like name + at least 3 rows:
       likely multiple series, pools, or trust filings.
       Drop all in 05.

    3. Same report_date + same word_count:
       likely duplicate or re-file.
       Keep first report in 05.

    4. Filename suggests non-10-K or placeholder:
       drop all in 05.

    5. Same report_date + different word_count:
       ambiguous, hold out for manual check.
    """
    if int(row["n_report_dates"]) > 1:
        reason_type = 1

    elif bool(row["securitization_fund_like_name"]) and int(row["n_rows"]) >= 3:
        reason_type = 2

    elif int(row["n_word_counts"]) == 1:
        reason_type = 3

    elif bool(row["any_non10k_like_filename"]) or bool(row["any_paper_placeholder"]):
        reason_type = 4

    else:
        reason_type = 5

    return REASON_LABELS[reason_type], reason_type


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT_CSV}")

    print("Reading initial 10-K sample...")
    df = pd.read_csv(INPUT_CSV, dtype={"cik": "string"}, low_memory=False)

    required_columns = ["cik", "report_year", "name", "tickers", "report_date", "filing_date", "url", "word_count"]
    missing_columns = [column for column in required_columns if column not in df.columns]

    if missing_columns:
        raise ValueError(
            "Input file is missing required columns: "
            + ", ".join(missing_columns)
            + f"\nPlease check file: {INPUT_CSV}"
        )

    df = df.copy()

    df["cik"] = df["cik"].map(normalize_cik)
    df["report_year"] = pd.to_numeric(df["report_year"], errors="raise").astype(int)
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
    df["word_count"] = pd.to_numeric(df["word_count"], errors="coerce")
    df["_filename"] = df["url"].map(filename_from_url)

    print("Finding duplicated cik-report_year groups...")
    group_sizes = df.groupby(["cik", "report_year"], dropna=False).size()
    duplicate_keys = group_sizes[group_sizes > 1].reset_index()[["cik", "report_year"]]

    duplicate_rows = df.merge(
        duplicate_keys,
        on=["cik", "report_year"],
        how="inner",
    ).copy()

    print(f"Duplicated company-year groups: {len(duplicate_keys):,}")
    print(f"Rows in duplicated groups: {len(duplicate_rows):,}")

    summary_rows = []

    for (cik, report_year), group in duplicate_rows.groupby(["cik", "report_year"], sort=True):
        group = group.copy()

        filenames = [str(x).strip() for x in group["_filename"] if not pd.isna(x) and str(x).strip()]

        row = {
            "cik": cik,
            "report_year": int(report_year),
            "name": first_nonmissing(group["name"]),
            "tickers": first_nonmissing(group["tickers"]),
            "n_rows": int(len(group)),
            "n_report_dates": int(group["report_date"].nunique(dropna=True)),
            "n_filing_dates": int(group["filing_date"].nunique(dropna=True)),
            "n_word_counts": int(group["word_count"].nunique(dropna=True)),
            "min_words": group["word_count"].min(),
            "max_words": group["word_count"].max(),
            "min_report": group["report_date"].min(),
            "max_report": group["report_date"].max(),
            "min_filing": group["filing_date"].min(),
            "max_filing": group["filing_date"].max(),
            "example_files": join_unique_text(group["_filename"]),
            "securitization_fund_like_name": securitization_fund_like_name(first_nonmissing(group["name"])),
            "any_non10k_like_filename": any_non10k_like_filename(filenames),
            "any_amend_like_filename": any_amend_like_filename(filenames),
            "any_paper_placeholder": any_paper_placeholder(filenames),
            "example_urls": join_urls(group["url"]),
        }

        reason_guess, reason_type = classify_reason(pd.Series(row))
        row["reason_guess"] = reason_guess
        row["reason_type"] = reason_type

        summary_rows.append(row)

    duplicated = pd.DataFrame(summary_rows)

    # Match the expected output column order.
    output_columns = [
        "cik",
        "report_year",
        "name",
        "tickers",
        "n_rows",
        "n_report_dates",
        "n_filing_dates",
        "n_word_counts",
        "min_words",
        "max_words",
        "min_report",
        "max_report",
        "min_filing",
        "max_filing",
        "example_files",
        "securitization_fund_like_name",
        "any_non10k_like_filename",
        "any_amend_like_filename",
        "any_paper_placeholder",
        "example_urls",
        "reason_guess",
        "reason_type",
    ]

    duplicated = duplicated[output_columns]

    # Format dates as YYYY-MM-DD in the output CSV.
    for column in ["min_report", "max_report", "min_filing", "max_filing"]:
        duplicated[column] = pd.to_datetime(duplicated[column], errors="coerce").dt.strftime("%Y-%m-%d")

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    print(f"Saving rebuilt duplicate classification file: {OUTPUT_CSV}")
    duplicated.to_csv(OUTPUT_CSV, index=False)

    print("\nDuplicate classification completed.")
    print(f"Output rows: {len(duplicated):,}")
    print("reason_type distribution:")
    print(duplicated["reason_type"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()