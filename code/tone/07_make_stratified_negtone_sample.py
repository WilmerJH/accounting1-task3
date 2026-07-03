"""
Create a report-year stratified random sample for LM negative tone analysis.

The script leaves the full deduplicated sample unchanged and writes a sampled
CSV plus a year-level sampling summary.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_CSV = PROJECT_ROOT / "data" / "generated" / "full_10k_sample_dedup.csv"
OUTPUT_CSV = (
    PROJECT_ROOT
    / "data"
    / "generated"
    / "full_10k_sample_dedup_stratified_1500_per_year.csv"
)
SUMMARY_CSV = (
    PROJECT_ROOT
    / "data"
    / "generated"
    / "full_10k_sample_dedup_stratified_1500_per_year_summary.csv"
)

YEAR_COLUMN = "report_year"
YEAR_MIN = 2002
YEAR_MAX = 2024
MAX_PER_YEAR = 1_500
RANDOM_STATE = 20260629


def relative_to_project(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT_CSV}")

    df = pd.read_csv(INPUT_CSV, dtype={"cik": "string"}, low_memory=False)
    if YEAR_COLUMN not in df.columns:
        raise ValueError(f"Input file must contain a '{YEAR_COLUMN}' column.")

    original_columns = list(df.columns)
    df = df.copy()
    df[YEAR_COLUMN] = pd.to_numeric(df[YEAR_COLUMN], errors="raise").astype(int)

    in_range = df[YEAR_COLUMN].between(YEAR_MIN, YEAR_MAX)
    if not in_range.all():
        outside_count = int((~in_range).sum())
        print(
            f"Warning: excluding {outside_count:,} rows outside "
            f"{YEAR_MIN}-{YEAR_MAX} or with invalid {YEAR_COLUMN}."
        )
    analysis_df = df.loc[in_range].copy()

    original_counts = (
        analysis_df.groupby(YEAR_COLUMN, sort=True).size().rename("original_count")
    )

    sampled_parts = []
    for _, group in analysis_df.groupby(YEAR_COLUMN, sort=True):
        sampled_parts.append(
            group.sample(
                n=min(len(group), MAX_PER_YEAR),
                random_state=RANDOM_STATE,
            )
        )
    sampled = (
        pd.concat(sampled_parts, ignore_index=True)
        .sample(frac=1, random_state=RANDOM_STATE)
        .reset_index(drop=True)
    )
    sampled = sampled[original_columns]

    sampled_counts = sampled.groupby(YEAR_COLUMN, sort=True).size().rename("sampled_count")
    summary = pd.concat([original_counts, sampled_counts], axis=1).fillna(0).reset_index()
    summary["original_count"] = summary["original_count"].astype(int)
    summary["sampled_count"] = summary["sampled_count"].astype(int)
    summary["sampling_rate"] = summary["sampled_count"] / summary["original_count"]

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    sampled.to_csv(OUTPUT_CSV, index=False)
    summary.to_csv(SUMMARY_CSV, index=False)

    year_min = int(sampled[YEAR_COLUMN].min()) if not sampled.empty else pd.NA
    year_max = int(sampled[YEAR_COLUMN].max()) if not sampled.empty else pd.NA

    print("Report-year stratified negtone sample created.")
    print(f"Original total rows: {len(df):,}")
    print(f"Sampled total rows: {len(sampled):,}")
    print(f"Year range: {year_min}-{year_max}")
    print("Sampled rows by report_year:")
    print(sampled_counts.to_string())
    print("Output paths:")
    print(f"- Sample: {relative_to_project(OUTPUT_CSV)}")
    print(f"- Summary: {relative_to_project(SUMMARY_CSV)}")


if __name__ == "__main__":
    main()
