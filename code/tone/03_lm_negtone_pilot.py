"""
使用 Loughran-McDonald 金融词典对 pilot 10-K 样本试算 negative tone。

默认输入:
data/generated/pilot_10k_sample_500.csv

默认输出:
data/generated/tone/pilot_lm_negtone.csv
data/generated/tone/pilot_lm_negtone_summary.csv

注意: 本脚本只处理本地已有的 10-K 文本文件，不会自动下载 SEC 文件。
"""

import argparse
import html
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd


# Windows 终端有时会使用非 UTF-8 编码；这里尽量保证中文进度信息正常显示。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "generated" / "pilot_10k_sample_500.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "generated" / "tone" / "pilot_lm_negtone.csv"

LOCAL_PATH_COLUMNS = ["file_path", "local_path", "html_path", "txt_path"]
FILENAME_COLUMNS = ["filename", "accession_number"]
IMPORTANT_COLUMNS = [
    "cik",
    "name",
    "tickers",
    "ticker",
    "filing_date",
    "report_date",
    "report_year",
    "url",
]
COMMON_TEXT_DIRS = [
    "data/raw",
    "data/external",
    "data/interim",
    "data/generated",
    "data/sec_filings",
    "data/10k",
    "data/10k_filings",
]
TEXT_EXTENSIONS = {".txt", ".html", ".htm"}


def find_lm_dictionary(project_root: Path) -> Path:
    """在 data/external/ 下自动查找 Loughran-McDonald Master Dictionary CSV。"""
    external_dir = project_root / "data" / "external"
    if not external_dir.exists():
        raise FileNotFoundError(
            f"找不到 data/external/ 目录: {external_dir}\n"
            "请把 Loughran-McDonald dictionary CSV 放到 data/external/。"
        )

    candidates = []
    for path in external_dir.glob("*.csv"):
        name = path.name.lower()
        if "loughran" in name and "mcdonald" in name and "masterdictionary" in name:
            candidates.append(path)

    if not candidates:
        raise FileNotFoundError(
            "找不到 Loughran-McDonald Master Dictionary CSV。\n"
            "请把词典文件放到 data/external/，文件名中应包含 "
            "Loughran、McDonald、MasterDictionary，例如:\n"
            "data/external/Loughran-McDonald_MasterDictionary_1993-2024.csv"
        )

    candidates = sorted(candidates, key=lambda x: x.name, reverse=True)
    return candidates[0]


def load_lm_negative_words(dictionary_path: Path) -> set[str]:
    """读取 LM 词典，并用 Negative != 0 的规则构建负面词集合。"""
    print(f"正在读取 Loughran-McDonald 词典: {dictionary_path}")
    dictionary = pd.read_csv(dictionary_path, low_memory=False)

    required_columns = ["Word", "Negative"]
    missing_columns = [col for col in required_columns if col not in dictionary.columns]
    if missing_columns:
        raise ValueError(
            "LM 词典缺少必要列: "
            + ", ".join(missing_columns)
            + f"\n请检查词典文件: {dictionary_path}"
        )

    negative_flag = pd.to_numeric(dictionary["Negative"], errors="coerce").fillna(0)
    words = dictionary.loc[negative_flag != 0, "Word"].dropna().astype(str).str.upper()
    negative_words = set(words)
    print(f"LM negative word 数量: {len(negative_words):,}")
    return negative_words


def build_local_file_index(project_root: Path) -> dict[str, list[Path]]:
    """扫描常见目录，为本地 10-K 文本文件建立文件名索引。"""
    file_index: dict[str, list[Path]] = {}

    for relative_dir in COMMON_TEXT_DIRS:
        directory = project_root / relative_dir
        if not directory.exists():
            continue

        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            file_index.setdefault(path.name.lower(), []).append(path)

    return file_index


def _is_missing(value: object) -> bool:
    """判断 CSV 单元格是否为空。"""
    if pd.isna(value):
        return True
    return str(value).strip() == ""


def _try_path(value: object, project_root: Path) -> Path | None:
    """尝试把 CSV 中的路径值解析为实际存在的本地文件路径。"""
    if _is_missing(value):
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


def _filename_from_url(url_value: object) -> str | None:
    """从 SEC URL 中提取文件名。"""
    if _is_missing(url_value):
        return None

    parsed = urlparse(str(url_value).strip())
    filename = Path(unquote(parsed.path)).name
    return filename if filename else None


def find_filing_text_path(
    row: pd.Series,
    project_root: Path,
    file_index: dict[str, list[Path]] | None = None,
) -> Path | None:
    """为单条 pilot 记录定位本地 10-K 文本文件。"""
    # 优先使用 CSV 中明确给出的本地路径列。
    for column in LOCAL_PATH_COLUMNS:
        if column not in row.index:
            continue
        path = _try_path(row[column], project_root)
        if path is not None:
            return path

    # 再尝试使用 filename 或 accession_number 这类标识列做文件名匹配。
    lookup_names = []
    for column in FILENAME_COLUMNS:
        if column in row.index and not _is_missing(row[column]):
            lookup_names.append(str(row[column]).strip())

    url_filename = _filename_from_url(row["url"]) if "url" in row.index else None
    if url_filename:
        lookup_names.append(url_filename)

    if file_index is None:
        file_index = build_local_file_index(project_root)

    for name in lookup_names:
        direct_path = _try_path(name, project_root)
        if direct_path is not None:
            return direct_path

        matched_paths = file_index.get(Path(name).name.lower(), [])
        if matched_paths:
            return matched_paths[0]

    return None


def read_filing_text(path: Path) -> str:
    """读取 10-K 文本文件，尽量兼容不同编码。"""
    raw_bytes = path.read_bytes()
    for encoding in ["utf-8", "latin-1", "cp1252"]:
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def clean_html_or_text(raw_text: str) -> str:
    """清洗 HTML 或纯文本，去除标签和多余空白。"""
    text = raw_text
    looks_like_html = bool(re.search(r"<\s*(html|body|div|table|p|span|document)\b", text, flags=re.I))

    if looks_like_html:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = soup.get_text(" ")
        except ImportError:
            print("提示: 未安装 bs4，正在使用 regex fallback 去除 HTML 标签。")
            text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
            text = re.sub(r"(?s)<[^>]+>", " ", text)

    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _find_part_candidates(text: str, part_label: str) -> list[int]:
    """查找 PART I / PART II / PART III 的候选位置。"""
    pattern = re.compile(rf"\bPART\s+{part_label}\b\.?", flags=re.I)
    return [match.start() for match in pattern.finditer(text)]


def extract_part_i_ii(text: str) -> tuple[str, str, bool]:
    """尽量提取正文中的 Part I 到 Part III 之前的文本。"""
    part_i_positions = _find_part_candidates(text, "I")
    part_ii_positions = _find_part_candidates(text, "II")
    part_iii_positions = _find_part_candidates(text, "III")

    candidates = []
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

        # 过短区间通常更像目录；10-K 正文 Part I+II 一般应有较长文本。
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

    # 优先选择更像正文的组合；通常正文区间更长，且不会出现在文件最开头的目录里。
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
    return text[best["part_i"] : best["part_iii"]], "part_i_ii", True


def compute_lm_negtone(text: str, negative_words: set[str]) -> tuple[int, int, float | None]:
    """根据 LM negative word set 计算 negative tone。"""
    tokens = re.findall(r"[A-Za-z]+", text)
    total_words = len(tokens)
    if total_words == 0:
        return 0, 0, None

    negative_count = sum(1 for token in tokens if token.upper() in negative_words)
    negtone = negative_count / total_words
    return total_words, negative_count, negtone


def _important_columns(input_df: pd.DataFrame) -> list[str]:
    """保留原始 pilot CSV 中重要的识别列。"""
    return [column for column in IMPORTANT_COLUMNS if column in input_df.columns]


def _make_summary(results: pd.DataFrame) -> pd.DataFrame:
    """生成 pilot 试运行结果的简单汇总。"""
    negtone = pd.to_numeric(results["negtone"], errors="coerce")
    total_words = pd.to_numeric(results["total_words"], errors="coerce")
    negative_words = pd.to_numeric(results["negative_words"], errors="coerce")

    summary = {
        "pilot_total_rows": len(results),
        "text_found_count": int(results["text_found"].sum()),
        "part_i_ii_success_count": int(results["section_extraction_success"].sum()),
        "full_text_fallback_count": int((results["section_used"] == "full_text_fallback").sum()),
        "missing_file_count": int((results["parse_status"] == "missing_file").sum()),
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


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="对 pilot 10-K 样本试算 Loughran-McDonald negative tone。"
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT),
        help="pilot 样本 CSV 路径，默认 data/generated/pilot_10k_sample_500.csv",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="结果 CSV 路径，默认 data/generated/tone/pilot_lm_negtone.csv",
    )
    return parser.parse_args()


def main() -> None:
    """主流程。"""
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    summary_path = output_path.with_name(output_path.stem + "_summary.csv")

    print("开始对 pilot 样本试算 LM negative tone...")
    print(f"输入文件: {input_path}")
    print(f"输出文件: {output_path}")
    print(f"summary 文件: {summary_path}")

    if not input_path.exists():
        raise FileNotFoundError(f"找不到输入 pilot CSV: {input_path}")

    dictionary_path = find_lm_dictionary(PROJECT_ROOT)
    negative_words = load_lm_negative_words(dictionary_path)

    print("正在读取 pilot 样本...")
    pilot = pd.read_csv(input_path, dtype={"cik": "string"}, low_memory=False)
    print(f"pilot 样本读取完成，共 {len(pilot):,} 条记录。")
    print("pilot CSV 实际列名:")
    print(", ".join(pilot.columns))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print("正在扫描常见目录中的本地 10-K 文本文件...")
    file_index = build_local_file_index(PROJECT_ROOT)
    indexed_file_count = sum(len(paths) for paths in file_index.values())
    print(f"已索引本地文本文件数量: {indexed_file_count:,}")

    id_columns = _important_columns(pilot)
    results = []

    for row_number, (_, row) in enumerate(pilot.iterrows(), start=1):
        if row_number == 1 or row_number % 50 == 0 or row_number == len(pilot):
            print(f"处理进度: {row_number:,}/{len(pilot):,}")

        result = {column: row.get(column, pd.NA) for column in id_columns}
        result.update(
            {
                "text_found": False,
                "section_used": pd.NA,
                "section_extraction_success": False,
                "total_words": pd.NA,
                "negative_words": pd.NA,
                "negtone": pd.NA,
                "parse_status": "missing_file",
                "source_file": pd.NA,
            }
        )

        try:
            text_path = find_filing_text_path(row, PROJECT_ROOT, file_index=file_index)
            if text_path is None:
                results.append(result)
                continue

            result["text_found"] = True
            result["source_file"] = str(text_path)

            raw_text = read_filing_text(text_path)
            clean_text = clean_html_or_text(raw_text)
            section_text, section_used, extraction_success = extract_part_i_ii(clean_text)
            total_words, negative_count, negtone = compute_lm_negtone(section_text, negative_words)

            result["section_used"] = section_used
            result["section_extraction_success"] = extraction_success
            result["total_words"] = total_words
            result["negative_words"] = negative_count
            result["negtone"] = negtone

            if total_words == 0:
                result["parse_status"] = "no_tokens"
            else:
                result["parse_status"] = "ok" if extraction_success else "ok_full_text_fallback"

        except Exception as exc:
            result["parse_status"] = f"error: {type(exc).__name__}: {exc}"

        results.append(result)

    results_df = pd.DataFrame(results)
    summary_df = _make_summary(results_df)

    print(f"正在保存逐条结果: {output_path}")
    results_df.to_csv(output_path, index=False)

    print(f"正在保存 summary: {summary_path}")
    summary_df.to_csv(summary_path, index=False)

    print("\nLM negative tone pilot 试运行完成。")
    print("主要结果:")
    print(f"- pilot 样本总行数: {len(results_df):,}")
    print(f"- 成功找到文本数量: {int(results_df['text_found'].sum()):,}")
    print(f"- 成功提取 Part I + Part II 数量: {int(results_df['section_extraction_success'].sum()):,}")
    print(f"- fallback 到全文数量: {int((results_df['section_used'] == 'full_text_fallback').sum()):,}")
    print(f"- 缺失文件数量: {int((results_df['parse_status'] == 'missing_file').sum()):,}")
    print("输出文件路径:")
    print(f"- 逐条结果: {output_path}")
    print(f"- summary: {summary_path}")


if __name__ == "__main__":
    main()
