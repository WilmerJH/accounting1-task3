"""
Utility functions for resolving and downloading SEC filing documents.

This module contains reusable SEC URL-resolution logic originally used in the
pilot 10-K download script. It is intended to be imported by full-sample scripts
such as 06_run_full_lm_negtone.py.

Main public function:
    resolve_download_url(session, original_url, headers, sleep_seconds)

Given a SEC URL, this function returns the primary 10-K document URL when
possible. It supports both:
1. Direct text/HTML filing document URLs.
2. SEC filing detail pages ending in -index.html.
"""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


DIRECT_DOCUMENT_EXTENSIONS = {".txt", ".htm", ".html"}
SKIP_EXTENSIONS = {
    ".xml",
    ".xsd",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".pdf",
    ".zip",
    ".xlsx",
}

TRANSIENT_HTTP_STATUS = {429, 403, 503}
MAX_RETRIES = 3


def is_valid_sec_url(url: str) -> bool:
    """Return whether the URL is a requestable SEC URL."""
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower().endswith("sec.gov")


def request_with_retries(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    sleep_seconds: float,
) -> tuple[requests.Response | None, str, int | None]:
    """
    Request a URL, retrying transient HTTP errors.

    Returns:
        response:
            requests.Response if a response was received, otherwise None.
        status:
            One of "success", "http_error", or "request_exception".
        http_status:
            HTTP status code if available.
    """
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
                print(
                    f"Note: request exception on attempt {attempt}. "
                    f"Waiting {wait_seconds:.1f} seconds before retrying."
                )
                time.sleep(wait_seconds)
                continue

            return None, "request_exception", last_status

    return None, "request_exception", last_status


def is_direct_document_url(url: str) -> bool:
    """
    Return whether the URL points directly to a text or HTML primary document.

    SEC detail pages often end in -index.html and should not be treated as
    direct primary documents.
    """
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
    """Return whether a document link is a likely text/HTML filing document."""
    suffix = Path(urlparse(href).path).suffix.lower()
    return suffix in DIRECT_DOCUMENT_EXTENSIONS and suffix not in SKIP_EXTENSIONS


def find_primary_doc_url(index_html: str, index_url: str) -> str | None:
    """
    Find the primary 10-K document URL from a SEC filing detail page.

    The function searches SEC filing tables and prefers rows whose filing type
    is exactly 10-K. If no exact 10-K row is found, it returns the first allowed
    text/HTML document link as a fallback.
    """
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
    """
    Resolve a SEC filing URL to the primary document URL.

    Args:
        session:
            Existing requests.Session.
        original_url:
            URL from the sample CSV.
        headers:
            SEC request headers, including a valid User-Agent.
        sleep_seconds:
            Seconds to wait after each SEC request.

    Returns:
        download_url:
            Primary document URL if found, otherwise None.
        status:
            One of:
            - "success"
            - "missing_url"
            - "invalid_url"
            - "http_error"
            - "request_exception"
            - "primary_doc_not_found"
        http_status:
            HTTP status code if available.
    """
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

    response, status, http_status = request_with_retries(
        session=session,
        url=url,
        headers=headers,
        sleep_seconds=sleep_seconds,
    )

    if status != "success" or response is None:
        return None, status, http_status

    primary_doc_url = find_primary_doc_url(response.text, url)

    if primary_doc_url is None:
        return None, "primary_doc_not_found", http_status

    return primary_doc_url, "success", http_status