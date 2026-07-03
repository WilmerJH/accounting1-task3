"""
Create the initial 10-K sample and descriptive statistics.

This script does not modify the raw file data/external/10k_word_counts.csv.
Output files are saved to data/generated/.
"""

import sys
from pathlib import Path

import pandas as pd


# Some Windows terminals use non-UTF-8 encodings; keep progress messages readable.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# -----------------------------
# Path settings
# -----------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_FILE = PROJECT_ROOT / "data" / "external" / "10k_word_counts.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "generated"

INITIAL_SAMPLE_FILE = OUTPUT_DIR / "initial_10k_sample_2002_2024.csv"
YEAR_SUMMARY_FILE = OUTPUT_DIR / "sample_size_by_year.csv"


def require_columns(df: pd.DataFrame, required_columns: list[str]) -> None:
    """Check that required columns exist and raise a clear error if any are missing."""
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(
            "Input file is missing required columns: "
            + ", ".join(missing_columns)
            + f"\nPlease check file: {INPUT_FILE}"
        )


def normalize_download_success(series: pd.Series) -> pd.Series:
    """Normalize the download_success column to booleans for filtering successful downloads."""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)

    true_values = {"true", "1", "yes", "y", "t"}
    return series.astype(str).str.strip().str.lower().isin(true_values)


def count_missing_values(df: pd.DataFrame, possible_columns: list[str]) -> int | None:
    """Count missing values for a field group; return None if no relevant column exists."""
    existing_columns = [col for col in possible_columns if col in df.columns]
    if not existing_columns:
        return None

    target_col = existing_columns[0]
    values_as_text = df[target_col].astype(str).str.strip()
    return int(df[target_col].isna().sum() + (values_as_text == "").sum())


def main() -> None:
    print("Starting initial 10-K sample and descriptive statistics generation...")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory confirmed: {OUTPUT_DIR}")

    print(f"Reading raw file: {INPUT_FILE}")
    df = pd.read_csv(INPUT_FILE, dtype={"cik": "string"}, low_memory=False)
    print(f"Raw file loaded with {len(df):,} records.")

    require_columns(df, ["cik", "filing_date", "report_date"])

    # Parse date columns to pandas datetime; unparseable dates become NaT.
    print("Parsing filing_date and report_date fields...")
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")

    missing_report_date = int(df["report_date"].isna().sum())
    if missing_report_date > 0:
        print(f"Note: {missing_report_date:,} records have unparseable or missing report_date values.")

    # Use the year from report_date as report_year and filter to 2002-2024.
    df["report_year"] = df["report_date"].dt.year
    sample = df[df["report_year"].between(2002, 2024, inclusive="both")].copy()
    sample["report_year"] = sample["report_year"].astype("int64")
    print(f"Records remaining after filtering report_year to 2002-2024: {len(sample):,}.")

    # If download_success exists, keep only successfully downloaded records.
    if "download_success" in sample.columns:
        before_filter = len(sample)
        sample = sample[normalize_download_success(sample["download_success"])].copy()
        removed = before_filter - len(sample)
        print(f"Filtered on download_success == True and removed {removed:,} records.")
    else:
        print("Note: download_success column not found; no download-success filter was applied.")

    # Summarize the overall sample.
    num_observations = int(len(sample))
    num_unique_ciks = int(sample["cik"].nunique(dropna=True))
    missing_ticker_count = count_missing_values(sample, ["tickers", "ticker"])
    missing_url_count = count_missing_values(sample, ["url"])

    if "file_size_in_bytes" in sample.columns:
        file_size_bytes = pd.to_numeric(sample["file_size_in_bytes"], errors="coerce").fillna(0)
        estimated_file_size_gb = float(file_size_bytes.sum() / (1024**3))
    else:
        file_size_bytes = None
        estimated_file_size_gb = None
        print("Note: file_size_in_bytes column not found; total file size cannot be estimated.")

    # Build the annual sample-size summary.
    print("Generating annual sample-size summary...")
    year_summary = (
        sample.groupby("report_year", dropna=False)
        .agg(
            num_10k_observations=("cik", "size"),
            num_unique_ciks=("cik", "nunique"),
        )
        .reset_index()
        .sort_values("report_year")
    )

    if file_size_bytes is not None:
        sample["_file_size_gb_for_summary"] = file_size_bytes / (1024**3)
        year_file_size = (
            sample.groupby("report_year", dropna=False)["_file_size_gb_for_summary"]
            .sum()
            .reset_index(name="estimated_file_size_gb")
        )
        year_summary = year_summary.merge(year_file_size, on="report_year", how="left")
        sample = sample.drop(columns=["_file_size_gb_for_summary"])

    print(f"Saving 2002-2024 initial sample: {INITIAL_SAMPLE_FILE}")
    sample.to_csv(INITIAL_SAMPLE_FILE, index=False)

    print(f"Saving annual sample-size summary: {YEAR_SUMMARY_FILE}")
    year_summary.to_csv(YEAR_SUMMARY_FILE, index=False)

    print("\nDescriptive statistics generation completed.")
    print("Output file paths:")
    print(f"- 2002-2024 initial sample: {INITIAL_SAMPLE_FILE}")
    print(f"- Annual sample-size summary: {YEAR_SUMMARY_FILE}")

    print("\nMain sample-size summary:")
    print(f"- Number of 10-K observations: {num_observations:,}")
    print(f"- Number of unique CIKs: {num_unique_ciks:,}")
    if missing_ticker_count is None:
        print("- Observations missing ticker information: tickers/ticker column not found")
    else:
        print(f"- Observations missing ticker information: {missing_ticker_count:,}")
    if missing_url_count is None:
        print("- Observations missing URL: url column not found")
    else:
        print(f"- Observations missing URL: {missing_url_count:,}")
    if estimated_file_size_gb is None:
        print("- Estimated total file size: file_size_in_bytes column not found")
    else:
        print(f"- Estimated total file size: {estimated_file_size_gb:,.3f} GB")


if __name__ == "__main__":
    main()
