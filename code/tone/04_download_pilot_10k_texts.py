"""
Download 10-K text files for the pilot sample and create a new pilot CSV with local paths.

Default input:
data/generated/pilot_10k_sample_500.csv

Default output:
data/generated/pilot_10k_sample_500_with_paths.csv

Download directory:
data/pulled/sec_filings/10k_pilot/

Notes:
1. This script accesses the SEC website, so pass a real User-Agent, for example:
   --user-agent "Your Name your.email@example.com"
2. By default, the script waits 1 second after each request to follow SEC fair access.
3. After downloads finish, the script automatically calls 03_lm_negtone_pilot.py
   to recalculate LM negative tone.
"""

import argparse
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


# Some Windows terminals use non-UTF-8 encodings; keep progress messages readable.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "generated" / "pilot_10k_sample_500.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "generated" / "pilot_10k_sample_500_with_paths.csv"
DEFAULT_DOWNLOAD_DIR = PROJECT_ROOT / "data" / "pulled" / "sec_filings" / "10k_pilot"
DEFAULT_NEGTONE_OUTPUT = PROJECT_ROOT / "data" / "generated" / "tone" / "pilot_lm_negtone.csv"

DIRECT_DOCUMENT_EXTENSIONS = {".txt", ".htm", ".html"}
SKIP_EXTENSIONS = {".xml", ".xsd", ".jpg", ".jpeg", ".png", ".gif", ".pdf", ".zip", ".xlsx"}
TRANSIENT_HTTP_STATUS = {429, 403, 503}
MAX_RETRIES = 3


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Download 10-K text files in the pilot sample.")
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT),
        help="Pilot CSV path; default is data/generated/pilot_10k_sample_500.csv",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="New CSV path with local file paths; default is data/generated/pilot_10k_sample_500_with_paths.csv",
    )
    parser.add_argument(
        "--download-dir",
        default=str(DEFAULT_DOWNLOAD_DIR),
        help="Directory for saved 10-K text files; default is data/sec_filings/10k_pilot/",
    )
    parser.add_argument(
        "--user-agent",
        default=None,
        help='SEC request User-Agent; use a real name and email, for example "Your Name your.email@example.com"',
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Seconds to wait after each SEC request; default is 1.0",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N records for testing, for example --limit 5",
    )
    parser.add_argument(
        "--skip-negtone",
        action="store_true",
        help="Only download and create the CSV with paths; do not automatically run 03_lm_negtone_pilot.py",
    )
    return parser.parse_args()


def resolve_project_path(path_value: str) -> Path:
    """Resolve a command-line path to an absolute path."""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def make_sec_headers(user_agent: str) -> dict[str, str]:
    """Build SEC request headers."""
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }


def is_valid_sec_url(url: str) -> bool:
    """Check whether the URL is a requestable SEC URL."""
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower().endswith("sec.gov")


def request_with_retries(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    sleep_seconds: float,
) -> tuple[requests.Response | None, str, int | None]:
    """Request a URL, retrying 429/403/503 responses up to 3 times with increasing waits."""
    last_status = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, headers=headers, timeout=30)
            last_status = response.status_code
            time.sleep(sleep_seconds)

            if response.status_code == 200:
                return response, "success", response.status_code

            if response.status_code in TRANSIENT_HTTP_STATUS and attempt < MAX_RETRIES:
                wait_seconds = sleep_seconds * attempt * 2
                print(
                    f"Note: HTTP {response.status_code}; request attempt {attempt} failed. "
                    f"Waiting {wait_seconds:.1f} seconds before retrying."
                )
                time.sleep(wait_seconds)
                continue

            return response, "http_error", response.status_code

        except requests.RequestException:
            if attempt < MAX_RETRIES:
                wait_seconds = sleep_seconds * attempt * 2
                print(f"Note: request exception. Waiting {wait_seconds:.1f} seconds before retrying.")
                time.sleep(wait_seconds)
                continue
            return None, "request_exception", last_status

    return None, "request_exception", last_status


def is_direct_document_url(url: str) -> bool:
    """Return whether the URL points directly to a text or HTML primary document."""
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix in DIRECT_DOCUMENT_EXTENSIONS and "-index.html" not in url.lower()


def is_filing_detail_page(url: str) -> bool:
    """Return whether the URL is an SEC filing detail page."""
    path_lower = urlparse(url).path.lower()
    return path_lower.endswith("-index.html") or "browse-edgar" in path_lower


def _clean_cell_text(cell) -> str:
    """Extract text from an HTML table cell."""
    return cell.get_text(" ", strip=True) if cell is not None else ""


def _is_allowed_document_href(href: str) -> bool:
    """Exclude XML, image, PDF, and other non-primary document links."""
    suffix = Path(urlparse(href).path).suffix.lower()
    return suffix in DIRECT_DOCUMENT_EXTENSIONS and suffix not in SKIP_EXTENSIONS


def find_primary_doc_url(index_html: str, index_url: str) -> str | None:
    """Find the 10-K primary document in the SEC detail page's Document Format Files table."""
    soup = BeautifulSoup(index_html, "html.parser")

    table_candidates = []
    for table in soup.find_all("table"):
        table_text = table.get_text(" ", strip=True).lower()
        if "document format files" in table_text or "sequence" in table_text:
            table_candidates.append(table)

    if not table_candidates:
        table_candidates = soup.find_all("table")

    fallback_url = None
    for table in table_candidates:
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            row_texts = [_clean_cell_text(cell) for cell in cells]
            row_type = ""
            if len(row_texts) >= 4:
                row_type = row_texts[3].upper()
            elif len(row_texts) >= 2:
                row_type = row_texts[-1].upper()

            link = row.find("a", href=True)
            if link is None:
                continue

            href = link["href"]
            if not _is_allowed_document_href(href):
                continue

            absolute_url = urljoin(index_url, href)
            if row_type == "10-K":
                return absolute_url

            if fallback_url is None:
                fallback_url = absolute_url

    return fallback_url


def resolve_download_url(
    session: requests.Session,
    original_url: str,
    headers: dict[str, str],
    sleep_seconds: float,
) -> tuple[str | None, str, int | None]:
    """Resolve a pilot URL to the primary document URL that should be downloaded."""
    if pd.isna(original_url) or str(original_url).strip() == "":
        return None, "missing_url", None

    url = str(original_url).strip()
    if not is_valid_sec_url(url):
        return None, "invalid_url", None

    if is_direct_document_url(url):
        return url, "success", None

    if not is_filing_detail_page(url):
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix in DIRECT_DOCUMENT_EXTENSIONS:
            return url, "success", None

    response, status, http_status = request_with_retries(session, url, headers, sleep_seconds)
    if status != "success" or response is None:
        return None, status, http_status

    primary_doc_url = find_primary_doc_url(response.text, url)
    if primary_doc_url is None:
        return None, "primary_doc_not_found", http_status

    return primary_doc_url, "success", http_status


def accession_from_url(url: str) -> str | None:
    """Extract an accession number from an SEC URL path, preferring the accession directory."""
    parts = [part for part in urlparse(url).path.split("/") if part]
    for part in reversed(parts[:-1]):
        compact = part.replace("-", "")
        if re.fullmatch(r"\d{18}", compact):
            return f"{compact[:10]}-{compact[10:12]}-{compact[12:]}"
        if re.fullmatch(r"\d{10}-\d{2}-\d{6}", part):
            return part
    return None


def safe_filename_part(value: object, fallback: str) -> str:
    """Clean one filename component into a safe string."""
    if pd.isna(value) or str(value).strip() == "":
        text = fallback
    else:
        text = str(value).strip()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)


def target_file_path(row: pd.Series, row_number: int, download_url: str, download_dir: Path) -> Path:
    """Generate a stable and traceable local filename."""
    cik = safe_filename_part(row.get("cik"), f"row{row_number:04d}")
    report_year = safe_filename_part(row.get("report_year"), "unknown_year")
    accession = accession_from_url(download_url) or f"row{row_number:04d}"
    accession = safe_filename_part(accession, f"row{row_number:04d}")
    return download_dir / f"{cik}_{report_year}_{accession}.txt"


def relative_to_project(path: Path) -> str:
    """Return a path string relative to the project root."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def download_one_filing(
    row: pd.Series,
    row_number: int,
    session: requests.Session,
    headers: dict[str, str],
    sleep_seconds: float,
    download_dir: Path,
) -> dict[str, object]:
    """Download the 10-K primary document for one pilot record."""
    result = {
        "local_path": pd.NA,
        "download_success": False,
        "download_status": "missing_url",
        "source_url": row.get("url", pd.NA),
        "http_status": pd.NA,
        "downloaded_at": pd.NA,
    }

    download_url, resolve_status, resolve_http_status = resolve_download_url(
        session=session,
        original_url=row.get("url", pd.NA),
        headers=headers,
        sleep_seconds=sleep_seconds,
    )
    result["download_status"] = resolve_status
    result["http_status"] = resolve_http_status

    if download_url is None:
        return result

    result["source_url"] = download_url
    output_file = target_file_path(row, row_number, download_url, download_dir)
    result["local_path"] = relative_to_project(output_file)

    if output_file.exists() and output_file.stat().st_size > 0:
        result["download_success"] = True
        result["download_status"] = "already_exists"
        result["downloaded_at"] = datetime.fromtimestamp(
            output_file.stat().st_mtime, tz=timezone.utc
        ).isoformat()
        return result

    response, status, http_status = request_with_retries(
        session=session,
        url=download_url,
        headers=headers,
        sleep_seconds=sleep_seconds,
    )
    result["http_status"] = http_status

    if status != "success" or response is None:
        result["download_status"] = status
        return result

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(response.content)

    if output_file.stat().st_size == 0:
        result["download_status"] = "empty_file"
        return result

    result["download_success"] = True
    result["download_status"] = "success"
    result["downloaded_at"] = datetime.now(timezone.utc).isoformat()
    return result


def prepare_output_dataframe(pilot: pd.DataFrame) -> pd.DataFrame:
    """Prepare the output DataFrame while preserving the original download_success column."""
    output = pilot.copy()
    if "download_success" in output.columns and "input_download_success" not in output.columns:
        output = output.rename(columns={"download_success": "input_download_success"})

    for column in [
        "local_path",
        "download_success",
        "download_status",
        "source_url",
        "http_status",
        "downloaded_at",
    ]:
        output[column] = pd.NA

    return output


def run_negtone_script(input_csv: Path, output_csv: Path) -> int:
    """Call the existing LM negtone script after downloads finish."""
    command = [
        sys.executable,
        str(PROJECT_ROOT / "code" / "tone" / "03_lm_negtone_pilot.py"),
        "--input",
        str(input_csv),
        "--output",
        str(output_csv),
    ]
    print("\nStarting automatic LM negtone analysis:")
    print(" ".join(command))
    completed = subprocess.run(command, cwd=PROJECT_ROOT)
    return completed.returncode


def main() -> None:
    """Run the main workflow."""
    args = parse_args()
    if args.user_agent is None or args.user_agent.strip() == "":
        raise SystemExit(
            "Error: downloading SEC files requires --user-agent.\n"
            "Use your real name and email, for example:\n"
            'python code\\tone\\04_download_pilot_10k_texts.py '
            '--limit 5 --user-agent "Your Name your.email@example.com"\n'
            "Do not use a fake email address."
        )

    input_path = resolve_project_path(args.input)
    output_path = resolve_project_path(args.output)
    download_dir = resolve_project_path(args.download_dir)

    print("Starting pilot 10-K text file downloads...")
    print(f"Input CSV: {input_path}")
    print(f"Output CSV: {output_path}")
    print(f"Download directory: {download_dir}")

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    pilot = pd.read_csv(input_path, dtype={"cik": "string"}, low_memory=False)
    if "url" not in pilot.columns:
        raise ValueError(f"Input CSV is missing the url column: {input_path}")

    print("Actual pilot CSV columns:")
    print(", ".join(pilot.columns))

    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be a positive integer")
        pilot_to_process = pilot.head(args.limit).copy()
        print(f"Test mode: processing only the first {len(pilot_to_process):,} records.")
    else:
        pilot_to_process = pilot.copy()

    output = prepare_output_dataframe(pilot_to_process)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)

    headers = make_sec_headers(args.user_agent)
    session = requests.Session()

    for row_number, (index, row) in enumerate(pilot_to_process.iterrows(), start=1):
        result = download_one_filing(
            row=row,
            row_number=row_number,
            session=session,
            headers=headers,
            sleep_seconds=args.sleep,
            download_dir=download_dir,
        )

        for column, value in result.items():
            output.loc[index, column] = value

        if row_number % 25 == 0 or row_number == len(pilot_to_process):
            print(f"Processed {row_number}/{len(pilot_to_process)}")

    print(f"Saving new pilot CSV with local paths: {output_path}")
    output.to_csv(output_path, index=False)

    status_counts = output["download_status"].value_counts(dropna=False)
    success_count = int((output["download_status"] == "success").sum())
    already_exists_count = int((output["download_status"] == "already_exists").sum())
    total_success_count = int(output["download_success"].fillna(False).astype(bool).sum())
    failure_count = int(len(output) - total_success_count)

    print("\nDownload summary:")
    print(f"- Total rows: {len(output):,}")
    print(f"- Successful downloads: {success_count:,}")
    print(f"- Already-existing files: {already_exists_count:,}")
    print(f"- Failures: {failure_count:,}")
    print("- download_status distribution:")
    for status, count in status_counts.items():
        print(f"  {status}: {count:,}")

    if args.skip_negtone:
        print("\nSkipped automatic LM negtone analysis. To run it manually:")
        print(
            f"{sys.executable} code\\tone\\03_lm_negtone_pilot.py "
            f"--input {output_path} --output {DEFAULT_NEGTONE_OUTPUT}"
        )
        return

    returncode = run_negtone_script(output_path, DEFAULT_NEGTONE_OUTPUT)
    if returncode != 0:
        print("\nNote: automatic LM negtone script failed. You can run the following command manually:")
        print(
            f"{sys.executable} code\\tone\\03_lm_negtone_pilot.py "
            f"--input {output_path} --output {DEFAULT_NEGTONE_OUTPUT}"
        )


if __name__ == "__main__":
    main()
