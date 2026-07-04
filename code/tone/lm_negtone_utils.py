"""
Utility functions for Loughran-McDonald negative tone analysis on 10-K filings.

This module contains reusable text-location, parsing, section-extraction, and
LM negative tone functions originally used in the pilot negative tone script.

Main public functions:
    find_lm_dictionary(project_root)
    load_lm_negative_words(dictionary_path)
    build_local_file_index(project_root)
    find_filing_text_path(row, project_root, file_index=None)
    read_filing_text(path)
    clean_html_or_text(raw_text)
    extract_part_i_ii(text)
    compute_lm_negtone(text, negative_words)
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd


LOCAL_PATH_COLUMNS = ["file_path", "local_path", "html_path", "txt_path"]
FILENAME_COLUMNS = ["filename", "accession_number"]

COMMON_TEXT_DIRS = [
    "data/raw",
    "data/external",
    "data/pulled",
    "data/pulled/sec_filings"
    "data/interim",
    "data/generated",
    "data/sec_filings",
    "data/10k",
    "data/10k_filings",
]

TEXT_EXTENSIONS = {".txt", ".html", ".htm"}


def find_lm_dictionary(project_root: Path) -> Path:
    """
    Find the Loughran-McDonald Master Dictionary CSV under data/external/.

    The expected filename should contain:
        Loughran
        McDonald
        MasterDictionary

    Example:
        data/external/Loughran-McDonald_MasterDictionary_1993-2024.csv
    """
    external_dir = project_root / "data" / "external"

    if not external_dir.exists():
        raise FileNotFoundError(
            f"Missing data/external directory: {external_dir}\n"
            "Please put the Loughran-McDonald dictionary CSV under data/external/."
        )

    candidates: list[Path] = []

    for path in external_dir.glob("*.csv"):
        name = path.name.lower()
        if "loughran" in name and "mcdonald" in name and "masterdictionary" in name:
            candidates.append(path)

    if not candidates:
        raise FileNotFoundError(
            "Could not find the Loughran-McDonald Master Dictionary CSV.\n"
            "Please put the dictionary file under data/external/.\n"
            "The filename should contain Loughran, McDonald, and MasterDictionary.\n"
            "Example:\n"
            "data/external/Loughran-McDonald_MasterDictionary_1993-2024.csv"
        )

    candidates = sorted(candidates, key=lambda x: x.name, reverse=True)
    return candidates[0]


def load_lm_negative_words(dictionary_path: Path) -> set[str]:
    """
    Load negative words from the Loughran-McDonald dictionary.

    The function uses the standard rule:
        Negative != 0

    Required columns:
        Word
        Negative
    """
    print(f"Reading Loughran-McDonald dictionary: {dictionary_path}")
    dictionary = pd.read_csv(dictionary_path, low_memory=False)

    required_columns = ["Word", "Negative"]
    missing_columns = [col for col in required_columns if col not in dictionary.columns]

    if missing_columns:
        raise ValueError(
            "LM dictionary is missing required columns: "
            + ", ".join(missing_columns)
            + f"\nPlease check dictionary file: {dictionary_path}"
        )

    negative_flag = pd.to_numeric(dictionary["Negative"], errors="coerce").fillna(0)

    words = (
        dictionary.loc[negative_flag != 0, "Word"]
        .dropna()
        .astype(str)
        .str.upper()
    )

    negative_words = set(words)

    print(f"Number of LM negative words: {len(negative_words):,}")
    return negative_words


def build_local_file_index(project_root: Path) -> dict[str, list[Path]]:
    """
    Scan common project directories and build a filename index for local 10-K files.

    Returns:
        Dictionary mapping lowercase filename to a list of matching paths.
    """
    file_index: dict[str, list[Path]] = {}

    for relative_dir in COMMON_TEXT_DIRS:
        directory = project_root / relative_dir

        if not directory.exists():
            continue

        for path in directory.rglob("*"):
            if not path.is_file():
                continue

            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue

            file_index.setdefault(path.name.lower(), []).append(path)

    return file_index


def is_missing(value: object) -> bool:
    """Return whether a CSV-like value is missing or blank."""
    if pd.isna(value):
        return True

    return str(value).strip() == ""


def try_path(value: object, project_root: Path) -> Path | None:
    """
    Try to resolve a CSV path-like value to an existing local file.

    The function checks both:
        1. The path as written.
        2. The path relative to project_root.
    """
    if is_missing(value):
        return None

    text_value = str(value).strip().strip('"').strip("'")
    path = Path(text_value)

    candidates = [path]

    if not path.is_absolute():
        candidates.append(project_root / path)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


def filename_from_url(url_value: object) -> str | None:
    """Extract a filename from a SEC URL."""
    if is_missing(url_value):
        return None

    parsed = urlparse(str(url_value).strip())
    filename = Path(unquote(parsed.path)).name

    return filename if filename else None


def find_filing_text_path(
    row: pd.Series,
    project_root: Path,
    file_index: dict[str, list[Path]] | None = None,
) -> Path | None:
    """
    Locate a local 10-K text or HTML file for one sample row.

    Search priority:
        1. Explicit local path columns:
           file_path, local_path, html_path, txt_path

        2. Filename-like columns:
           filename, accession_number

        3. Filename extracted from the SEC URL.

        4. Filename lookup in the local file index.
    """
    for column in LOCAL_PATH_COLUMNS:
        if column not in row.index:
            continue

        path = try_path(row[column], project_root)

        if path is not None:
            return path

    lookup_names: list[str] = []

    for column in FILENAME_COLUMNS:
        if column in row.index and not is_missing(row[column]):
            lookup_names.append(str(row[column]).strip())

    url_filename = filename_from_url(row["url"]) if "url" in row.index else None

    if url_filename:
        lookup_names.append(url_filename)

    if file_index is None:
        file_index = build_local_file_index(project_root)

    for name in lookup_names:
        direct_path = try_path(name, project_root)

        if direct_path is not None:
            return direct_path

        matched_paths = file_index.get(Path(name).name.lower(), [])

        if matched_paths:
            return matched_paths[0]

    return None


def read_filing_text(path: Path) -> str:
    """
    Read a local filing text file with several common encodings.

    Encoding fallback order:
        utf-8
        latin-1
        cp1252
        utf-8 with replacement
    """
    raw_bytes = path.read_bytes()

    for encoding in ["utf-8", "latin-1", "cp1252"]:
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw_bytes.decode("utf-8", errors="replace")


def clean_html_or_text(raw_text: str) -> str:
    """
    Clean raw HTML or plain text filing content.

    If the text appears to be HTML, the function uses BeautifulSoup to remove
    tags and script/style/noscript blocks. If bs4 is unavailable, it falls back
    to regex-based tag removal.
    """
    text = raw_text

    looks_like_html = bool(
        re.search(
            r"<\s*(html|body|div|table|p|span|document)\b",
            text,
            flags=re.I,
        )
    )

    if looks_like_html:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(text, "html.parser")

            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()

            text = soup.get_text(" ")

        except ImportError:
            print("Note: bs4 is not installed; using regex fallback to remove HTML tags.")
            text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
            text = re.sub(r"(?s)<[^>]+>", " ", text)

    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def find_part_candidates(text: str, part_label: str) -> list[int]:
    """Find candidate positions for PART I, PART II, or PART III."""
    pattern = re.compile(rf"\bPART\s+{part_label}\b\.?", flags=re.I)
    return [match.start() for match in pattern.finditer(text)]


def extract_part_i_ii(text: str) -> tuple[str, str, bool]:
    """
    Try to extract the main Part I + Part II section of a 10-K filing.

    The function searches for:
        PART I
        PART II
        PART III

    It returns text from PART I to immediately before PART III.

    If no plausible section is found, it returns the full text as fallback.

    Returns:
        section_text:
            Extracted section or full text fallback.
        section_used:
            "part_i_ii" or "full_text_fallback".
        extraction_success:
            True if Part I + Part II was successfully extracted.
    """
    part_i_positions = find_part_candidates(text, "I")
    part_ii_positions = find_part_candidates(text, "II")
    part_iii_positions = find_part_candidates(text, "III")

    candidates: list[dict[str, object]] = []
    text_length = len(text)

    for part_i in part_i_positions:
        later_part_ii = [pos for pos in part_ii_positions if pos > part_i]

        if not later_part_ii:
            continue

        part_ii = later_part_ii[0]
        later_part_iii = [pos for pos in part_iii_positions if pos > part_ii]

        if not later_part_iii:
            continue

        part_iii = later_part_iii[0]
        section_length = part_iii - part_i

        # Very short ranges are likely to be table-of-contents entries rather
        # than the actual filing body.
        if section_length < 5_000:
            continue

        starts_after_opening_noise = part_i > text_length * 0.01

        candidates.append(
            {
                "part_i": part_i,
                "part_ii": part_ii,
                "part_iii": part_iii,
                "section_length": section_length,
                "starts_after_opening_noise": starts_after_opening_noise,
            }
        )

    if not candidates:
        return text, "full_text_fallback", False

    # Prefer a candidate that appears after opening metadata/table-of-contents
    # noise, has a long section length, and occurs later in the document.
    candidates = sorted(
        candidates,
        key=lambda item: (
            item["starts_after_opening_noise"],
            item["section_length"],
            item["part_i"],
        ),
        reverse=True,
    )

    best = candidates[0]

    return (
        text[int(best["part_i"]) : int(best["part_iii"])],
        "part_i_ii",
        True,
    )


def compute_lm_negtone(
    text: str,
    negative_words: set[str],
) -> tuple[int, int, float | None]:
    """
    Compute Loughran-McDonald negative tone.

    Formula:
        negtone = negative_words / total_words

    Tokenization:
        English alphabetic tokens only, using regex [A-Za-z]+.
    """
    tokens = re.findall(r"[A-Za-z]+", text)
    total_words = len(tokens)

    if total_words == 0:
        return 0, 0, None

    negative_count = sum(1 for token in tokens if token.upper() in negative_words)
    negtone = negative_count / total_words

    return total_words, negative_count, negtone