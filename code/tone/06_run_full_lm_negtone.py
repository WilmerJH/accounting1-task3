"""
Run Loughran-McDonald negative tone analysis on the deduplicated full 10-K sample.

The core parsing and tone logic is reused from the pilot script:
code/tone/03_lm_negtone_pilot.py. This full-sample runner adds SEC download
caching, resumable batch writes, and per-row error handling.

Example:
    python code/tone/06_run_full_lm_negtone.py --user-agent "Name email@example.com"

For a cache-only dry run using already downloaded texts:
    python code/tone/06_run_full_lm_negtone.py --cache-only
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "generated" / "full_10k_sample_dedup.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "generated" / "full_lm_negtone_results.csv"
DEFAULT_SUMMARY = PROJECT_ROOT / "data" / "generated" / "full_lm_negtone_summary.csv"
DEFAULT_DOWNLOAD_DIR = PROJECT_ROOT / "data" / "generated" / "10k_texts_full"

PILOT_NEGTONE_SCRIPT = PROJECT_ROOT / "code" / "tone" / "03_lm_negtone_pilot.py"
PILOT_DOWNLOAD_SCRIPT = PROJECT_ROOT / "code" / "tone" / "04_download_pilot_10k_texts.py"

ID_COLUMNS = [
    "original_row_number",
    "cik",
    "name",
    "tickers",
    "ticker",
    "filing_date",
    "report_date",
    "report_year",
    "url",
    "reason_type",
    "dedup_action",
]
OUTPUT_COLUMNS = [
    "original_row_number",
    "cik",
    "name",
    "tickers",
    "ticker",
    "filing_date",
    "report_date",
    "report_year",
    "url",
    "accession_number",
    "reason_type",
    "dedup_action",
    "text_found",
    "download_attempted",
    "download_success",
    "download_status",
    "http_status",
    "section_used",
    "section_extraction_success",
    "used_full_text_fallback",
    "total_words",
    "negative_words",
    "negtone",
    "parse_status",
    "failure_reason",
    "source_file",
    "processed_at",
]
TRANSIENT_HTTP_STATUS = {429, 403, 503}
MAX_RETRIES = 3


def load_module(script_path: Path, module_name: str):
    """Load an existing script as a module without requiring package imports."""
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pilot_negtone = load_module(PILOT_NEGTONE_SCRIPT, "pilot_negtone")
pilot_download = load_module(PILOT_DOWNLOAD_SCRIPT, "pilot_download")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run LM negative tone analysis on full deduplicated 10-K sample."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Input dedup sample CSV.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Row-level output CSV.")
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY), help="Summary output CSV.")
    parser.add_argument(
        "--download-dir",
        default=str(DEFAULT_DOWNLOAD_DIR),
        help="Directory for cached full-sample 10-K text files.",
    )
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("SEC_USER_AGENT"),
        help="SEC User-Agent. Can also be set with SEC_USER_AGENT.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Seconds to wait after each SEC request. Default respects SEC rate limits.",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Do not download; only use already cached local files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N rows after resume filtering.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Flush row-level results after this many newly processed rows.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing result and summary files instead of resuming.",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="When resuming, retry rows that have non-ok parse_status values.",
    )
    parser.add_argument(
        "--max-text-bytes",
        type=int,
        default=25_000_000,
        help="Skip parsing local text files larger than this many bytes. Use 0 for no limit.",
    )
    return parser.parse_args()


def resolve_project_path(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def is_missing(value: object) -> bool:
    if pd.isna(value):
        return True
    return str(value).strip() == ""


def accession_from_url(url_value: object) -> str | pd.NA:
    if is_missing(url_value):
        return pd.NA

    parts = [part for part in urlparse(str(url_value).strip()).path.split("/") if part]
    for part in reversed(parts):
        compact = part.replace("-", "")
        if re.fullmatch(r"\d{18}", compact):
            return f"{compact[:10]}-{compact[10:12]}-{compact[12:]}"
        if re.fullmatch(r"\d{10}-\d{2}-\d{6}", part):
            return part
    return pd.NA


def safe_filename_part(value: object, fallback: str) -> str:
    if is_missing(value):
        text = fallback
    else:
        text = str(value).strip()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)


def relative_to_project(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def target_file_path(row: pd.Series, row_number: int, download_dir: Path) -> Path:
    cik = safe_filename_part(row.get("cik"), f"row{row_number:06d}")
    report_year = safe_filename_part(row.get("report_year"), "unknown_year")
    accession = row.get("accession_number", pd.NA)
    if is_missing(accession):
        accession = accession_from_url(row.get("url", pd.NA))
    accession = safe_filename_part(accession, f"row{row_number:06d}")
    return download_dir / f"{cik}_{report_year}_{accession}.txt"


def build_accession_file_lookup(file_index: dict[str, list[Path]]) -> dict[str, Path]:
    """Map accession numbers found in local filenames to cached text paths."""
    lookup: dict[str, Path] = {}
    accession_pattern = re.compile(r"\d{10}-\d{2}-\d{6}")
    for paths in file_index.values():
        for path in paths:
            match = accession_pattern.search(path.name)
            if match and match.group(0) not in lookup:
                lookup[match.group(0)] = path
    return lookup


def find_by_accession_lookup(
    row: pd.Series, accession_lookup: dict[str, Path]
) -> Path | None:
    """Find a cached local filing by accession number extracted from the row."""
    accession = row.get("accession_number", pd.NA)
    if is_missing(accession):
        accession = accession_from_url(row.get("url", pd.NA))
    if is_missing(accession):
        return None
    return accession_lookup.get(str(accession).strip())


def make_sec_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }


def request_with_retries(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    sleep_seconds: float,
) -> tuple[requests.Response | None, str, int | pd.NA]:
    last_status: int | pd.NA = pd.NA

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, headers=headers, timeout=30)
            last_status = response.status_code
            time.sleep(sleep_seconds)

            if response.status_code == 200:
                return response, "success", response.status_code

            if response.status_code in TRANSIENT_HTTP_STATUS and attempt < MAX_RETRIES:
                time.sleep(sleep_seconds * attempt * 2)
                continue

            return response, "http_error", response.status_code

        except requests.RequestException:
            if attempt < MAX_RETRIES:
                time.sleep(sleep_seconds * attempt * 2)
                continue
            return None, "request_exception", last_status

    return None, "request_exception", last_status


def download_text_file(
    row: pd.Series,
    row_number: int,
    session: requests.Session,
    headers: dict[str, str],
    sleep_seconds: float,
    download_dir: Path,
) -> tuple[Path | None, dict[str, object]]:
    """Download one filing text into the cache directory."""
    result = {
        "download_attempted": True,
        "download_success": False,
        "download_status": "missing_url",
        "http_status": pd.NA,
    }

    url = row.get("url", pd.NA)
    if is_missing(url):
        return None, result

    download_url, resolve_status, resolve_http_status = pilot_download.resolve_download_url(
        session=session,
        original_url=str(url).strip(),
        headers=headers,
        sleep_seconds=sleep_seconds,
    )
    result["download_status"] = resolve_status
    result["http_status"] = resolve_http_status

    if download_url is None:
        return None, result

    output_file = target_file_path(row, row_number, download_dir)
    if output_file.exists() and output_file.stat().st_size > 0:
        result["download_success"] = True
        result["download_status"] = "already_exists"
        return output_file, result

    response, status, http_status = request_with_retries(
        session=session,
        url=download_url,
        headers=headers,
        sleep_seconds=sleep_seconds,
    )
    result["http_status"] = http_status

    if status != "success" or response is None:
        result["download_status"] = status
        return None, result

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(response.content)
    if output_file.stat().st_size == 0:
        result["download_status"] = "empty_file"
        return None, result

    result["download_success"] = True
    result["download_status"] = "success"
    return output_file, result


def initial_result(row: pd.Series) -> dict[str, object]:
    result = {column: row.get(column, pd.NA) for column in ID_COLUMNS}
    result["accession_number"] = row.get("accession_number", pd.NA)
    result.update(
        {
            "text_found": False,
            "download_attempted": False,
            "download_success": False,
            "download_status": pd.NA,
            "http_status": pd.NA,
            "section_used": pd.NA,
            "section_extraction_success": False,
            "used_full_text_fallback": False,
            "total_words": pd.NA,
            "negative_words": pd.NA,
            "negtone": pd.NA,
            "parse_status": "missing_file",
            "failure_reason": "file missing",
            "source_file": pd.NA,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return result


def process_one_row(
    row: pd.Series,
    row_number: int,
    negative_words: set[str],
    file_index: dict[str, list[Path]],
    accession_lookup: dict[str, Path],
    session: requests.Session | None,
    headers: dict[str, str] | None,
    sleep_seconds: float,
    download_dir: Path,
    cache_only: bool,
    max_text_bytes: int,
) -> dict[str, object]:
    result = initial_result(row)

    try:
        text_path = pilot_negtone.find_filing_text_path(
            row=row,
            project_root=PROJECT_ROOT,
            file_index=file_index,
        )
        if text_path is None:
            text_path = find_by_accession_lookup(row, accession_lookup)

        if text_path is None:
            target_path = target_file_path(row, row_number, download_dir)
            if target_path.exists() and target_path.stat().st_size > 0:
                text_path = target_path

        if text_path is None and not cache_only and session is not None and headers is not None:
            text_path, download_result = download_text_file(
                row=row,
                row_number=row_number,
                session=session,
                headers=headers,
                sleep_seconds=sleep_seconds,
                download_dir=download_dir,
            )
            result.update(download_result)

        if text_path is None:
            if cache_only:
                result["parse_status"] = "missing_file"
                result["failure_reason"] = "file missing in local cache"
            elif result["download_attempted"]:
                result["parse_status"] = "download_failed"
                result["failure_reason"] = f"download failed: {result['download_status']}"
            else:
                result["parse_status"] = "missing_file"
                result["failure_reason"] = "file missing"
            return result

        result["text_found"] = True
        result["source_file"] = relative_to_project(text_path)

        if max_text_bytes > 0 and text_path.stat().st_size > max_text_bytes:
            result["parse_status"] = "parse_skipped_large_file"
            result["failure_reason"] = (
                f"local text file exceeds --max-text-bytes "
                f"({text_path.stat().st_size} > {max_text_bytes})"
            )
            return result

        raw_text = pilot_negtone.read_filing_text(text_path)
        clean_text = pilot_negtone.clean_html_or_text(raw_text)
        if clean_text.strip() == "":
            result["parse_status"] = "no_valid_text"
            result["failure_reason"] = "no valid text after cleaning"
            return result

        section_text, section_used, extraction_success = pilot_negtone.extract_part_i_ii(
            clean_text
        )
        total_words, negative_count, negtone = pilot_negtone.compute_lm_negtone(
            section_text, negative_words
        )

        result["section_used"] = section_used
        result["section_extraction_success"] = extraction_success
        result["used_full_text_fallback"] = section_used == "full_text_fallback"
        result["total_words"] = total_words
        result["negative_words"] = negative_count
        result["negtone"] = negtone

        if total_words == 0:
            result["parse_status"] = "no_tokens"
            result["failure_reason"] = "no valid text tokens"
        else:
            result["parse_status"] = "ok" if extraction_success else "ok_full_text_fallback"
            result["failure_reason"] = pd.NA

    except Exception as exc:
        result["parse_status"] = "parse_failed"
        result["failure_reason"] = f"{type(exc).__name__}: {exc}"

    return result


def completed_row_ids(output_path: Path, retry_failed: bool) -> set[str]:
    if not output_path.exists():
        return set()

    existing = pd.read_csv(output_path, dtype={"cik": "string"}, low_memory=False)
    if "original_row_number" not in existing.columns:
        return set()

    if retry_failed and "parse_status" in existing.columns:
        existing = existing[
            existing["parse_status"].isin(["ok", "ok_full_text_fallback", "no_tokens"])
        ]

    return set(existing["original_row_number"].astype("string"))


def prune_failed_rows_for_retry(output_path: Path) -> int:
    """Keep only successful rows before a retry-failed run to avoid duplicates."""
    if not output_path.exists():
        return 0

    existing = pd.read_csv(output_path, dtype={"cik": "string"}, low_memory=False)
    if "parse_status" not in existing.columns:
        return 0

    success_statuses = ["ok", "ok_full_text_fallback", "no_tokens"]
    keep = existing[existing["parse_status"].isin(success_statuses)].copy()
    removed = len(existing) - len(keep)
    if removed > 0:
        keep.to_csv(output_path, index=False)
    return removed


def append_results(output_path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    batch = pd.DataFrame(rows)
    for column in OUTPUT_COLUMNS:
        if column not in batch.columns:
            batch[column] = pd.NA
    batch = batch[OUTPUT_COLUMNS]
    write_header = not output_path.exists()
    batch.to_csv(output_path, mode="a", index=False, header=write_header)


def make_summary(results: pd.DataFrame) -> pd.DataFrame:
    negtone = pd.to_numeric(results["negtone"], errors="coerce")
    total_words = pd.to_numeric(results["total_words"], errors="coerce")
    negative_words = pd.to_numeric(results["negative_words"], errors="coerce")
    text_found = results["text_found"].fillna(False).astype(bool)
    section_success = results["section_extraction_success"].fillna(False).astype(bool)

    summary = {
        "total_rows": len(results),
        "text_found_count": int(text_found.sum()),
        "part_i_ii_success_count": int(section_success.sum()),
        "full_text_fallback_count": int((results["section_used"] == "full_text_fallback").sum()),
        "missing_file_count": int((results["parse_status"] == "missing_file").sum()),
        "download_failed_count": int((results["parse_status"] == "download_failed").sum()),
        "parse_failed_count": int((results["parse_status"] == "parse_failed").sum()),
        "parse_skipped_large_file_count": int(
            (results["parse_status"] == "parse_skipped_large_file").sum()
        ),
        "no_valid_text_count": int((results["parse_status"] == "no_valid_text").sum()),
        "no_tokens_count": int((results["parse_status"] == "no_tokens").sum()),
        "negtone_success_count": int(negtone.notna().sum()),
        "negtone_mean": negtone.mean(),
        "negtone_median": negtone.median(),
        "negtone_std": negtone.std(),
        "negtone_min": negtone.min(),
        "negtone_max": negtone.max(),
        "total_words_mean": total_words.mean(),
        "total_words_median": total_words.median(),
        "total_words_min": total_words.min(),
        "total_words_max": total_words.max(),
        "negative_words_mean": negative_words.mean(),
        "negative_words_median": negative_words.median(),
        "negative_words_min": negative_words.min(),
        "negative_words_max": negative_words.max(),
    }
    return pd.DataFrame([summary])


def write_summary(output_path: Path, summary_path: Path) -> pd.DataFrame:
    results = pd.read_csv(output_path, dtype={"cik": "string"}, low_memory=False)
    summary = make_summary(results)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_path, index=False)
    return summary


def validate_input(sample: pd.DataFrame) -> None:
    if sample["reason_type"].isin([2, 4, 5]).any():
        counts = sample["reason_type"].value_counts(dropna=False).to_dict()
        raise ValueError(
            "Deduplicated input still contains reason_type 2, 4, or 5 rows: "
            + str(counts)
        )

    if sample["reason_type"].eq(3).any():
        reason3 = sample[sample["reason_type"].eq(3)]
        duplicate_reason3 = reason3.groupby(["cik", "report_year"]).size()
        duplicate_reason3 = duplicate_reason3[duplicate_reason3 > 1]
        if not duplicate_reason3.empty:
            raise ValueError(
                "reason_type 3 contains company-year groups with more than one row:\n"
                + duplicate_reason3.head(20).to_string()
            )


def main() -> None:
    args = parse_args()
    input_path = resolve_project_path(args.input)
    output_path = resolve_project_path(args.output)
    summary_path = resolve_project_path(args.summary)
    download_dir = resolve_project_path(args.download_dir)

    if not input_path.exists():
        raise FileNotFoundError(f"Missing input file: {input_path}")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive.")
    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be positive.")
    if not args.cache_only and is_missing(args.user_agent):
        raise SystemExit(
            "SEC downloads require --user-agent or SEC_USER_AGENT. "
            "Use --cache-only to process only existing local text files."
        )

    if args.overwrite:
        output_path.unlink(missing_ok=True)
        summary_path.unlink(missing_ok=True)
    elif args.retry_failed:
        removed_rows = prune_failed_rows_for_retry(output_path)
        if removed_rows:
            print(
                f"Retry-failed mode: removed {removed_rows:,} failed prior rows "
                "from the output before resuming."
            )

    print("Starting full-sample LM negative tone analysis...")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Summary: {summary_path}")
    print(f"Download cache: {download_dir}")
    print(f"Cache only: {args.cache_only}")

    sample = pd.read_csv(input_path, dtype={"cik": "string"}, low_memory=False)
    if "original_row_number" not in sample.columns:
        sample["original_row_number"] = range(1, len(sample) + 1)
    if "accession_number" not in sample.columns:
        sample["accession_number"] = sample["url"].map(accession_from_url).astype("string")

    validate_input(sample)
    print(f"Deduplicated input rows: {len(sample):,}")
    print("reason_type distribution in input:")
    print(sample["reason_type"].value_counts(dropna=False).sort_index().to_string())

    dictionary_path = pilot_negtone.find_lm_dictionary(PROJECT_ROOT)
    negative_words = pilot_negtone.load_lm_negative_words(dictionary_path)

    download_dir.mkdir(parents=True, exist_ok=True)
    print("Indexing local 10-K text files...")
    file_index = pilot_negtone.build_local_file_index(PROJECT_ROOT)
    indexed_file_count = sum(len(paths) for paths in file_index.values())
    accession_lookup = build_accession_file_lookup(file_index)
    print(f"Indexed local text files: {indexed_file_count:,}")
    print(f"Indexed local accession matches: {len(accession_lookup):,}")

    done_ids = completed_row_ids(output_path, retry_failed=args.retry_failed)
    todo = sample[~sample["original_row_number"].astype("string").isin(done_ids)].copy()
    if args.limit is not None:
        todo = todo.head(args.limit).copy()
    print(f"Already completed rows skipped: {len(done_ids):,}")
    print(f"Rows to process this run: {len(todo):,}")

    session = None
    headers = None
    if not args.cache_only:
        headers = make_sec_headers(str(args.user_agent).strip())
        session = requests.Session()

    batch_rows: list[dict[str, object]] = []
    start_time = time.time()
    for processed_count, (_, row) in enumerate(todo.iterrows(), start=1):
        row_number = int(row["original_row_number"])
        result = process_one_row(
            row=row,
            row_number=row_number,
            negative_words=negative_words,
            file_index=file_index,
            accession_lookup=accession_lookup,
            session=session,
            headers=headers,
            sleep_seconds=args.sleep,
            download_dir=download_dir,
            cache_only=args.cache_only,
            max_text_bytes=args.max_text_bytes,
        )
        batch_rows.append(result)

        if len(batch_rows) >= args.batch_size:
            append_results(output_path, batch_rows)
            batch_rows = []

        if processed_count == 1 or processed_count % 100 == 0 or processed_count == len(todo):
            elapsed = max(time.time() - start_time, 1)
            rate = processed_count / elapsed
            print(
                f"Processed {processed_count:,}/{len(todo):,} this run "
                f"({rate:.2f} rows/sec)"
            )

    append_results(output_path, batch_rows)

    if not output_path.exists():
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(output_path, index=False)

    summary = write_summary(output_path, summary_path)
    print("\nFull-sample LM negative tone summary:")
    print(summary.to_string(index=False))
    print("\nCompleted.")


if __name__ == "__main__":
    main()
