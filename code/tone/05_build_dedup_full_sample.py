"""
Build the deduplicated full 10-K sample for LM negative tone analysis.

Inputs are left untouched. The script starts from the full 2002-2024 sample,
joins the duplicated cik-report_year group classification, and applies the
agreed group-level handling rules:

* reason_type 2: drop all rows in the flagged company-year group.
* reason_type 3: keep the first report in the company-year group.
* reason_type 4: drop all rows in the flagged company-year group.
* reason_type 5: hold out all rows in the flagged company-year group.
* other rows: keep for this round of negative tone analysis.

For reason_type 3, "first report" is reproducible:
earliest filing/accepted date first, then report date, then accession number,
then the original source row order.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = PROJECT_ROOT / "data" / "generated"
DUPLICATE_DIR = GENERATED_DIR / "duplicate"

DEFAULT_SAMPLE_FILE = GENERATED_DIR / "initial_10k_sample_2002_2024.csv"
DEFAULT_DUPLICATE_GROUP_FILE = (
    DUPLICATE_DIR / "duplicated_cik_report_year_group_classification.csv"
)

DEDUP_SAMPLE_FILE = GENERATED_DIR / "full_10k_sample_dedup.csv"
HELDOUT_REASON5_FILE = GENERATED_DIR / "full_10k_sample_heldout_reason5.csv"
DROP_LOG_FILE = GENERATED_DIR / "full_10k_sample_dedup_drop_log.csv"
SUMMARY_FILE = GENERATED_DIR / "full_10k_sample_dedup_summary.csv"

COMPANY_ID_CANDIDATES = [
    "cik",
    "company_cik",
    "central_index_key",
    "gvkey",
    "permno",
    "permco",
    "ticker",
    "tickers",
    "company_id",
]
YEAR_CANDIDATES = [
    "report_year",
    "filing_year",
    "fyear",
    "fiscal_year",
    "year",
]
DATE_SORT_CANDIDATES = [
    "filing_date",
    "filed_at",
    "filed_date",
    "accepted_datetime",
    "acceptance_datetime",
    "accepted_at",
    "report_date",
    "period_of_report",
    "period_end_date",
]
ACCESSION_CANDIDATES = [
    "accession_number",
    "accession",
    "adsh",
    "accession_no",
]
URL_CANDIDATES = ["url", "filing_url", "source_url", "sec_url"]


def find_column(df: pd.DataFrame, candidates: list[str], label: str) -> str:
    """Find a column by case-insensitive candidate name."""
    lookup = {column.lower(): column for column in df.columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    raise ValueError(
        f"Could not identify {label} column. Tried: {', '.join(candidates)}. "
        f"Available columns: {', '.join(df.columns)}"
    )


def existing_columns(df: pd.DataFrame, candidates: list[str]) -> list[str]:
    """Return existing columns in candidate priority order."""
    lookup = {column.lower(): column for column in df.columns}
    found = []
    for candidate in candidates:
        column = lookup.get(candidate.lower())
        if column is not None and column not in found:
            found.append(column)
    return found


def is_missing_value(value: object) -> bool:
    if pd.isna(value):
        return True
    return str(value).strip() == ""


def normalize_company_id(series: pd.Series, column_name: str) -> pd.Series:
    """Normalize IDs for joining while preserving original columns in outputs."""
    values = series.astype("string").str.strip()
    column_lower = column_name.lower()

    if column_lower in {"cik", "company_cik", "central_index_key"}:
        digits = values.str.replace(r"\D", "", regex=True)
        normalized = digits.str.lstrip("0")
        return normalized.mask(normalized.eq(""), "0")

    return values.str.upper()


def normalize_year(series: pd.Series) -> pd.Series:
    """Normalize year-like values to nullable integer strings."""
    numeric_year = pd.to_numeric(series, errors="coerce")
    if numeric_year.notna().any():
        return numeric_year.astype("Int64").astype("string")

    parsed_dates = pd.to_datetime(series, errors="coerce")
    return parsed_dates.dt.year.astype("Int64").astype("string")


def accession_from_url(url_value: object) -> str | pd.NA:
    """Extract SEC accession number from a filing URL when possible."""
    if is_missing_value(url_value):
        return pd.NA

    path_parts = [part for part in urlparse(str(url_value).strip()).path.split("/") if part]
    for part in reversed(path_parts):
        compact = part.replace("-", "")
        if re.fullmatch(r"\d{18}", compact):
            return f"{compact[:10]}-{compact[10:12]}-{compact[12:]}"
        if re.fullmatch(r"\d{10}-\d{2}-\d{6}", part):
            return part
    return pd.NA


def choose_accession_column(df: pd.DataFrame) -> str:
    """Use an accession column if present; otherwise derive one from URL."""
    accession_columns = existing_columns(df, ACCESSION_CANDIDATES)
    if accession_columns:
        return accession_columns[0]

    url_columns = existing_columns(df, URL_CANDIDATES)
    if url_columns:
        df["accession_number"] = df[url_columns[0]].map(accession_from_url).astype("string")
        return "accession_number"

    df["accession_number"] = pd.NA
    return "accession_number"


def add_join_keys(
    df: pd.DataFrame, company_col: str, year_col: str, prefix: str
) -> pd.DataFrame:
    """Add normalized join keys without changing source columns."""
    df[f"_{prefix}_company_key"] = normalize_company_id(df[company_col], company_col)
    df[f"_{prefix}_year_key"] = normalize_year(df[year_col])
    return df


def prepare_drop_log(
    processed: pd.DataFrame,
    company_col: str,
    year_col: str,
    accession_col: str,
    url_col: str | None,
) -> pd.DataFrame:
    """Create one row for every dropped or held-out source observation."""
    log_rows = processed[processed["dedup_action"].ne("kept")].copy()

    output_columns = {
        "original_row_number": log_rows["original_row_number"],
        "company_id_column": company_col,
        "company_id": log_rows[company_col],
        "year_column": year_col,
        "year": log_rows[year_col],
        "accession_number": log_rows[accession_col],
        "reason_type": log_rows["reason_type"],
        "dedup_action": log_rows["dedup_action"],
        "drop_log_reason": log_rows["dedup_action"],
        "dedup_rule": log_rows["dedup_rule"],
    }

    if url_col is not None:
        output_columns["url"] = log_rows[url_col]

    optional_columns = [
        "name",
        "ticker",
        "tickers",
        "filing_date",
        "report_date",
        "word_count",
        "file_size_in_bytes",
    ]
    for column in optional_columns:
        if column in log_rows.columns and column not in output_columns:
            output_columns[column] = log_rows[column]

    return pd.DataFrame(output_columns)


def make_summary(
    sample: pd.DataFrame,
    processed: pd.DataFrame,
    duplicate_groups: pd.DataFrame,
    company_col: str,
    year_col: str,
    date_sort_cols: list[str],
    accession_col: str,
) -> pd.DataFrame:
    """Build a compact machine-readable summary table."""
    rows = []

    def add(metric: str, value: object, notes: str = "") -> None:
        rows.append({"metric": metric, "value": value, "notes": notes})

    add("input_rows", len(sample), "Rows in initial full 10-K sample before dedup handling.")
    add(
        "duplicate_company_year_groups",
        len(duplicate_groups),
        f"Groups from {DEFAULT_DUPLICATE_GROUP_FILE.relative_to(PROJECT_ROOT).as_posix()}.",
    )
    add("company_id_column", company_col, "Auto-detected company identifier column.")
    add("year_column", year_col, "Auto-detected year column.")
    add(
        "reason3_sort_rule",
        " > ".join(date_sort_cols + [accession_col, "original_row_number"]),
        "Ascending order; missing date/accession values sort last before original row fallback.",
    )

    for reason_type in [1, 2, 3, 4, 5]:
        reason_mask = processed["reason_type"].eq(reason_type)
        add(f"reason_type_{reason_type}_flagged_rows", int(reason_mask.sum()))
        add(
            f"reason_type_{reason_type}_flagged_groups",
            int(duplicate_groups["reason_type"].eq(reason_type).sum()),
        )

    action_counts = processed["dedup_action"].value_counts(dropna=False).to_dict()
    for action in [
        "dropped_reason2",
        "dropped_reason4",
        "heldout_reason5",
        "dropped_reason3_not_first_report",
    ]:
        add(f"{action}_rows", int(action_counts.get(action, 0)))

    add(
        "reason3_not_first_report_dropped_rows",
        int(action_counts.get("dropped_reason3_not_first_report", 0)),
        "Rows removed after keeping the first report per company-year in reason_type 3 groups.",
    )
    add("final_negtone_sample_rows", int(processed["dedup_action"].eq("kept").sum()))
    add(
        "kept_reason3_first_report_rows",
        int((processed["reason_type"].eq(3) & processed["dedup_action"].eq("kept")).sum()),
    )
    add(
        "unflagged_or_other_reason_rows_kept",
        int((processed["reason_type"].isna() | processed["reason_type"].eq(1)).sum()),
        "Includes unflagged rows and reason_type 1 duplicate groups retained for this round.",
    )

    return pd.DataFrame(rows)


def main() -> None:
    if not DEFAULT_SAMPLE_FILE.exists():
        raise FileNotFoundError(f"Missing input sample: {DEFAULT_SAMPLE_FILE}")
    if not DEFAULT_DUPLICATE_GROUP_FILE.exists():
        raise FileNotFoundError(f"Missing duplicate classification: {DEFAULT_DUPLICATE_GROUP_FILE}")

    print("Reading full 10-K sample and duplicate classification...")
    sample = pd.read_csv(DEFAULT_SAMPLE_FILE, dtype={"cik": "string"}, low_memory=False)
    duplicate_groups = pd.read_csv(
        DEFAULT_DUPLICATE_GROUP_FILE, dtype={"cik": "string"}, low_memory=False
    )

    sample_company_col = find_column(sample, COMPANY_ID_CANDIDATES, "sample company ID")
    sample_year_col = find_column(sample, YEAR_CANDIDATES, "sample year")
    duplicate_company_col = find_column(
        duplicate_groups, COMPANY_ID_CANDIDATES, "duplicate company ID"
    )
    duplicate_year_col = find_column(duplicate_groups, YEAR_CANDIDATES, "duplicate year")

    if "reason_type" not in duplicate_groups.columns:
        raise ValueError("Duplicate classification file must contain reason_type.")

    print(f"Sample company/year columns: {sample_company_col}, {sample_year_col}")
    print(f"Duplicate company/year columns: {duplicate_company_col}, {duplicate_year_col}")

    sample = sample.copy()
    duplicate_groups = duplicate_groups.copy()
    sample["original_row_number"] = range(1, len(sample) + 1)

    add_join_keys(sample, sample_company_col, sample_year_col, "sample")
    add_join_keys(duplicate_groups, duplicate_company_col, duplicate_year_col, "dup")

    reason_map = duplicate_groups[
        ["_dup_company_key", "_dup_year_key", "reason_type"]
    ].drop_duplicates()
    if reason_map.duplicated(["_dup_company_key", "_dup_year_key"]).any():
        duplicated_keys = reason_map[
            reason_map.duplicated(["_dup_company_key", "_dup_year_key"], keep=False)
        ]
        raise ValueError(
            "Duplicate classification has conflicting reason_type rows for the same key:\n"
            + duplicated_keys.to_string(index=False)
        )

    processed = sample.merge(
        reason_map,
        how="left",
        left_on=["_sample_company_key", "_sample_year_key"],
        right_on=["_dup_company_key", "_dup_year_key"],
    )
    processed["reason_type"] = pd.to_numeric(processed["reason_type"], errors="coerce").astype(
        "Int64"
    )

    accession_col = choose_accession_column(processed)
    url_columns = existing_columns(processed, URL_CANDIDATES)
    url_col = url_columns[0] if url_columns else None

    date_sort_cols = existing_columns(processed, DATE_SORT_CANDIDATES)
    for column in date_sort_cols:
        processed[f"_sort_{column}"] = pd.to_datetime(processed[column], errors="coerce")
    processed["_sort_accession"] = processed[accession_col].astype("string").str.strip()

    reason3_mask = processed["reason_type"].eq(3)
    processed["dedup_action"] = "kept"
    processed["dedup_rule"] = "kept_unflagged_or_reason1"
    processed.loc[processed["reason_type"].eq(2), "dedup_action"] = "dropped_reason2"
    processed.loc[processed["reason_type"].eq(2), "dedup_rule"] = (
        "reason_type 2: dropped all rows in flagged company-year group"
    )
    processed.loc[processed["reason_type"].eq(4), "dedup_action"] = "dropped_reason4"
    processed.loc[processed["reason_type"].eq(4), "dedup_rule"] = (
        "reason_type 4: dropped all rows in flagged company-year group"
    )
    processed.loc[processed["reason_type"].eq(5), "dedup_action"] = "heldout_reason5"
    processed.loc[processed["reason_type"].eq(5), "dedup_rule"] = (
        "reason_type 5: held out for later analysis, excluded from this negtone run"
    )

    if reason3_mask.any():
        sort_columns = (
            ["_sample_company_key", "_sample_year_key"]
            + [f"_sort_{column}" for column in date_sort_cols]
            + ["_sort_accession", "original_row_number"]
        )
        reason3_ordered = processed.loc[reason3_mask].sort_values(
            sort_columns,
            ascending=True,
            na_position="last",
            kind="mergesort",
        )
        first_reason3_indices = reason3_ordered.groupby(
            ["_sample_company_key", "_sample_year_key"], sort=False
        ).head(1).index

        reason3_drop_mask = reason3_mask & ~processed.index.isin(first_reason3_indices)
        processed.loc[reason3_mask, "dedup_rule"] = (
            "reason_type 3: kept first report by ascending "
            + " > ".join(date_sort_cols + [accession_col, "original_row_number"])
        )
        processed.loc[reason3_drop_mask, "dedup_action"] = (
            "dropped_reason3_not_first_report"
        )

    helper_columns = [
        column
        for column in processed.columns
        if column.startswith("_sample_")
        or column.startswith("_dup_")
        or column.startswith("_sort_")
    ]

    output_metadata_cols = [
        "original_row_number",
        "reason_type",
        "dedup_action",
        "dedup_rule",
    ]
    if accession_col not in processed.columns:
        output_metadata_cols.append("accession_number")

    original_columns = [column for column in sample.columns if not column.startswith("_sample_")]
    metadata_columns = [
        column
        for column in output_metadata_cols
        if column in processed.columns and column not in original_columns
    ]
    output_columns = original_columns + metadata_columns

    kept = processed[processed["dedup_action"].eq("kept")].copy()
    heldout = processed[processed["dedup_action"].eq("heldout_reason5")].copy()
    drop_log = prepare_drop_log(
        processed=processed,
        company_col=sample_company_col,
        year_col=sample_year_col,
        accession_col=accession_col,
        url_col=url_col,
    )
    summary = make_summary(
        sample=sample,
        processed=processed,
        duplicate_groups=duplicate_groups,
        company_col=sample_company_col,
        year_col=sample_year_col,
        date_sort_cols=date_sort_cols,
        accession_col=accession_col,
    )

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    kept.drop(columns=helper_columns, errors="ignore")[output_columns].to_csv(
        DEDUP_SAMPLE_FILE, index=False
    )
    heldout.drop(columns=helper_columns, errors="ignore")[output_columns].to_csv(
        HELDOUT_REASON5_FILE, index=False
    )
    drop_log.to_csv(DROP_LOG_FILE, index=False)
    summary.to_csv(SUMMARY_FILE, index=False)

    print("Dedup outputs created:")
    print(f"- {DEDUP_SAMPLE_FILE.relative_to(PROJECT_ROOT).as_posix()}: {len(kept):,} rows")
    print(f"- {HELDOUT_REASON5_FILE.relative_to(PROJECT_ROOT).as_posix()}: {len(heldout):,} rows")
    print(f"- {DROP_LOG_FILE.relative_to(PROJECT_ROOT).as_posix()}: {len(drop_log):,} rows")
    print(f"- {SUMMARY_FILE.relative_to(PROJECT_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
