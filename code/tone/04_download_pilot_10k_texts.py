"""
下载 pilot 样本对应的 10-K 文本文件，并生成带本地路径的新 pilot CSV。

默认输入:
data/generated/pilot_10k_sample_500.csv

默认输出:
data/generated/pilot_10k_sample_500_with_paths.csv

下载目录:
data/sec_filings/10k_pilot/

注意:
1. 本脚本会访问 SEC 网站，请务必传入真实的 User-Agent，例如:
   --user-agent "Your Name your.email@example.com"
2. 默认每次请求后等待 1 秒，以遵守 SEC fair access。
3. 下载结束后默认自动调用 03_lm_negtone_pilot.py 重新计算 LM negative tone。
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


# Windows 终端有时会使用非 UTF-8 编码；这里尽量保证中文进度信息正常显示。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "generated" / "pilot_10k_sample_500.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "generated" / "pilot_10k_sample_500_with_paths.csv"
DEFAULT_DOWNLOAD_DIR = PROJECT_ROOT / "data" / "sec_filings" / "10k_pilot"
DEFAULT_NEGTONE_OUTPUT = PROJECT_ROOT / "data" / "generated" / "tone" / "pilot_lm_negtone.csv"

DIRECT_DOCUMENT_EXTENSIONS = {".txt", ".htm", ".html"}
SKIP_EXTENSIONS = {".xml", ".xsd", ".jpg", ".jpeg", ".png", ".gif", ".pdf", ".zip", ".xlsx"}
TRANSIENT_HTTP_STATUS = {429, 403, 503}
MAX_RETRIES = 3


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="下载 pilot 样本中的 10-K 文本文件。")
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT),
        help="pilot CSV 路径，默认 data/generated/pilot_10k_sample_500.csv",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="带本地路径的新 CSV 路径，默认 data/generated/pilot_10k_sample_500_with_paths.csv",
    )
    parser.add_argument(
        "--download-dir",
        default=str(DEFAULT_DOWNLOAD_DIR),
        help="10-K 文本保存目录，默认 data/sec_filings/10k_pilot/",
    )
    parser.add_argument(
        "--user-agent",
        default=None,
        help='SEC 请求 User-Agent，请填写真实姓名和邮箱，例如 "Your Name your.email@example.com"',
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="每次 SEC 请求后的等待秒数，默认 1.0",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理前 N 条记录，用于测试，例如 --limit 5",
    )
    parser.add_argument(
        "--skip-negtone",
        action="store_true",
        help="只下载并生成带路径 CSV，不自动运行 03_lm_negtone_pilot.py",
    )
    return parser.parse_args()


def resolve_project_path(path_value: str) -> Path:
    """将命令行路径解析为绝对路径。"""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def make_sec_headers(user_agent: str) -> dict[str, str]:
    """构造 SEC 请求 headers。"""
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }


def is_valid_sec_url(url: str) -> bool:
    """检查 URL 是否是可请求的 SEC URL。"""
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower().endswith("sec.gov")


def request_with_retries(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    sleep_seconds: float,
) -> tuple[requests.Response | None, str, int | None]:
    """请求 URL；遇到 429/403/503 时最多重试 3 次并递增等待。"""
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
                    f"提示: HTTP {response.status_code}，第 {attempt} 次请求失败，"
                    f"等待 {wait_seconds:.1f} 秒后重试。"
                )
                time.sleep(wait_seconds)
                continue

            return response, "http_error", response.status_code

        except requests.RequestException:
            if attempt < MAX_RETRIES:
                wait_seconds = sleep_seconds * attempt * 2
                print(f"提示: 请求异常，等待 {wait_seconds:.1f} 秒后重试。")
                time.sleep(wait_seconds)
                continue
            return None, "request_exception", last_status

    return None, "request_exception", last_status


def is_direct_document_url(url: str) -> bool:
    """判断 URL 是否直接指向文本或 HTML 主文档。"""
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix in DIRECT_DOCUMENT_EXTENSIONS and "-index.html" not in url.lower()


def is_filing_detail_page(url: str) -> bool:
    """判断 URL 是否是 SEC filing detail page。"""
    path_lower = urlparse(url).path.lower()
    return path_lower.endswith("-index.html") or "browse-edgar" in path_lower


def _clean_cell_text(cell) -> str:
    """提取 HTML 表格单元格文本。"""
    return cell.get_text(" ", strip=True) if cell is not None else ""


def _is_allowed_document_href(href: str) -> bool:
    """排除 XML、图片、PDF 等非主文档。"""
    suffix = Path(urlparse(href).path).suffix.lower()
    return suffix in DIRECT_DOCUMENT_EXTENSIONS and suffix not in SKIP_EXTENSIONS


def find_primary_doc_url(index_html: str, index_url: str) -> str | None:
    """从 SEC detail page 的 Document Format Files 表里寻找 10-K 主文档。"""
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
    """把 pilot 中的 URL 解析成真正要下载的主文档 URL。"""
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
    """从 SEC URL 路径中提取 accession number，优先使用 accession 目录。"""
    parts = [part for part in urlparse(url).path.split("/") if part]
    for part in reversed(parts[:-1]):
        compact = part.replace("-", "")
        if re.fullmatch(r"\d{18}", compact):
            return f"{compact[:10]}-{compact[10:12]}-{compact[12:]}"
        if re.fullmatch(r"\d{10}-\d{2}-\d{6}", part):
            return part
    return None


def safe_filename_part(value: object, fallback: str) -> str:
    """将文件名组成部分清洗成安全字符串。"""
    if pd.isna(value) or str(value).strip() == "":
        text = fallback
    else:
        text = str(value).strip()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)


def target_file_path(row: pd.Series, row_number: int, download_url: str, download_dir: Path) -> Path:
    """生成稳定、可追踪的本地文件名。"""
    cik = safe_filename_part(row.get("cik"), f"row{row_number:04d}")
    report_year = safe_filename_part(row.get("report_year"), "unknown_year")
    accession = accession_from_url(download_url) or f"row{row_number:04d}"
    accession = safe_filename_part(accession, f"row{row_number:04d}")
    return download_dir / f"{cik}_{report_year}_{accession}.txt"


def relative_to_project(path: Path) -> str:
    """返回相对于项目根目录的路径字符串。"""
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
    """下载单条 pilot 记录对应的 10-K 主文档。"""
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
    """准备输出 DataFrame；保留原始 download_success，避免和本次下载状态混淆。"""
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
    """下载完成后调用现有的 LM negtone 脚本。"""
    command = [
        sys.executable,
        str(PROJECT_ROOT / "code" / "tone" / "03_lm_negtone_pilot.py"),
        "--input",
        str(input_csv),
        "--output",
        str(output_csv),
    ]
    print("\n开始自动运行 LM negtone 分析:")
    print(" ".join(command))
    completed = subprocess.run(command, cwd=PROJECT_ROOT)
    return completed.returncode


def main() -> None:
    """主流程。"""
    args = parse_args()
    if args.user_agent is None or args.user_agent.strip() == "":
        raise SystemExit(
            "错误: 下载 SEC 文件必须传入 --user-agent。\n"
            "请填写你自己的真实姓名和邮箱，例如:\n"
            'D:\\users\\anaconda3\\python.exe code\\tone\\04_download_pilot_10k_texts.py '
            '--limit 5 --user-agent "Your Name your.email@example.com"\n'
            "不要使用假的邮箱。"
        )

    input_path = resolve_project_path(args.input)
    output_path = resolve_project_path(args.output)
    download_dir = resolve_project_path(args.download_dir)

    print("开始下载 pilot 10-K 文本文件...")
    print(f"输入 CSV: {input_path}")
    print(f"输出 CSV: {output_path}")
    print(f"下载目录: {download_dir}")

    if not input_path.exists():
        raise FileNotFoundError(f"找不到输入文件: {input_path}")

    pilot = pd.read_csv(input_path, dtype={"cik": "string"}, low_memory=False)
    if "url" not in pilot.columns:
        raise ValueError(f"输入 CSV 缺少 url 列: {input_path}")

    print("pilot CSV 实际列名:")
    print(", ".join(pilot.columns))

    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit 必须是正整数")
        pilot_to_process = pilot.head(args.limit).copy()
        print(f"测试模式: 只处理前 {len(pilot_to_process):,} 条记录。")
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

    print(f"正在保存带本地路径的新 pilot CSV: {output_path}")
    output.to_csv(output_path, index=False)

    status_counts = output["download_status"].value_counts(dropna=False)
    success_count = int((output["download_status"] == "success").sum())
    already_exists_count = int((output["download_status"] == "already_exists").sum())
    total_success_count = int(output["download_success"].fillna(False).astype(bool).sum())
    failure_count = int(len(output) - total_success_count)

    print("\n下载 summary:")
    print(f"- 总行数: {len(output):,}")
    print(f"- 成功下载数量: {success_count:,}")
    print(f"- 已存在数量: {already_exists_count:,}")
    print(f"- 失败数量: {failure_count:,}")
    print("- download_status 分布:")
    for status, count in status_counts.items():
        print(f"  {status}: {count:,}")

    if args.skip_negtone:
        print("\n已跳过自动运行 LM negtone 分析。可手动运行:")
        print(
            f"{sys.executable} code\\tone\\03_lm_negtone_pilot.py "
            f"--input {output_path} --output {DEFAULT_NEGTONE_OUTPUT}"
        )
        return

    returncode = run_negtone_script(output_path, DEFAULT_NEGTONE_OUTPUT)
    if returncode != 0:
        print("\n提示: 自动运行 LM negtone 脚本失败。可手动运行以下命令:")
        print(
            f"{sys.executable} code\\tone\\03_lm_negtone_pilot.py "
            f"--input {output_path} --output {DEFAULT_NEGTONE_OUTPUT}"
        )


if __name__ == "__main__":
    main()
