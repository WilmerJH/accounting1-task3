"""
准备 10-K 负面语调研究的初始样本和 pilot 样本。

本脚本不会修改原始文件 data/external/10k_word_counts.csv。
输出文件会保存到 data/generated/。
"""

import sys
from pathlib import Path

import pandas as pd


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# -----------------------------
# 路径设置
# -----------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_FILE = PROJECT_ROOT / "data" / "external" / "10k_word_counts.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "generated"

INITIAL_SAMPLE_FILE = OUTPUT_DIR / "initial_10k_sample_2002_2024.csv"
YEAR_SUMMARY_FILE = OUTPUT_DIR / "sample_size_by_year.csv"
PILOT_SAMPLE_FILE = OUTPUT_DIR / "pilot_10k_sample_500.csv"


def require_columns(df: pd.DataFrame, required_columns: list[str]) -> None:
    """检查必要列是否存在；如果缺失，给出清楚的错误信息。"""
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(
            "输入文件缺少必要列: "
            + ", ".join(missing_columns)
            + f"\n请检查文件: {INPUT_FILE}"
        )


def normalize_download_success(series: pd.Series) -> pd.Series:
    """将 download_success 列统一转换为布尔值，便于筛选下载成功的记录。"""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)

    true_values = {"true", "1", "yes", "y", "t"}
    return series.astype(str).str.strip().str.lower().isin(true_values)


def count_missing_values(df: pd.DataFrame, possible_columns: list[str]) -> int | None:
    """统计某类字段的缺失值；如果相关列不存在，返回 None。"""
    existing_columns = [col for col in possible_columns if col in df.columns]
    if not existing_columns:
        return None

    target_col = existing_columns[0]
    return int(df[target_col].isna().sum() + (df[target_col].astype(str).str.strip() == "").sum())


def main() -> None:
    print("开始准备 10-K 初始样本...")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"找不到输入文件: {INPUT_FILE}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"已确认输出目录: {OUTPUT_DIR}")

    print(f"正在读取原始文件: {INPUT_FILE}")
    df = pd.read_csv(INPUT_FILE, dtype={"cik": "string"}, low_memory=False)
    print(f"原始文件读取完成，共 {len(df):,} 条记录。")

    require_columns(df, ["cik", "filing_date", "report_date"])

    # 将日期列解析为 pandas 日期类型；无法解析的日期会变成 NaT。
    print("正在解析 filing_date 和 report_date 日期字段...")
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")

    missing_report_date = int(df["report_date"].isna().sum())
    if missing_report_date > 0:
        print(f"提示: 有 {missing_report_date:,} 条记录的 report_date 无法解析或缺失。")

    # 使用 report_date 的年份作为报告年份，并筛选 2002-2024。
    df["report_year"] = df["report_date"].dt.year
    sample = df[df["report_year"].between(2002, 2024, inclusive="both")].copy()
    sample["report_year"] = sample["report_year"].astype("int64")
    print(f"筛选 report year 在 2002-2024 的记录后，剩余 {len(sample):,} 条。")

    # 如果存在 download_success 列，只保留下载成功的记录。
    if "download_success" in sample.columns:
        before_filter = len(sample)
        sample = sample[normalize_download_success(sample["download_success"])].copy()
        removed = before_filter - len(sample)
        print(f"已根据 download_success == True 筛选，剔除 {removed:,} 条记录。")
    else:
        print("提示: 未找到 download_success 列，因此未按下载成功状态筛选。")

    # 汇总总体样本信息。
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
        print("提示: 未找到 file_size_in_bytes 列，因此无法估计总文件大小。")

    # 生成年度层面的样本量汇总。
    print("正在生成年度样本量汇总...")
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

    # 保存筛选后的完整样本和年度汇总。
    print(f"正在保存 2002-2024 初始样本: {INITIAL_SAMPLE_FILE}")
    sample.to_csv(INITIAL_SAMPLE_FILE, index=False)

    print(f"正在保存年度样本量汇总: {YEAR_SUMMARY_FILE}")
    year_summary.to_csv(YEAR_SUMMARY_FILE, index=False)

    # 生成 pilot 样本。若可用记录不足 500，则保留全部。
    pilot_n = min(500, len(sample))
    print(f"正在生成 pilot 样本，目标样本量为 {pilot_n:,} 条...")
    if pilot_n < len(sample):
        pilot_sample = sample.sample(n=pilot_n, random_state=123)
    else:
        pilot_sample = sample.copy()

    print(f"正在保存 pilot 样本: {PILOT_SAMPLE_FILE}")
    pilot_sample.to_csv(PILOT_SAMPLE_FILE, index=False)

    print("\n样本准备完成。")
    print("输出文件路径:")
    print(f"- 2002-2024 初始样本: {INITIAL_SAMPLE_FILE}")
    print(f"- 年度样本量汇总: {YEAR_SUMMARY_FILE}")
    print(f"- pilot 样本: {PILOT_SAMPLE_FILE}")

    print("\n主要样本量汇总:")
    print(f"- 10-K 观测数量: {num_observations:,}")
    print(f"- 唯一 CIK 数量: {num_unique_ciks:,}")
    if missing_ticker_count is None:
        print("- 缺失 ticker 信息的观测数量: 未找到 tickers/ticker 列")
    else:
        print(f"- 缺失 ticker 信息的观测数量: {missing_ticker_count:,}")
    if missing_url_count is None:
        print("- 缺失 URL 的观测数量: 未找到 url 列")
    else:
        print(f"- 缺失 URL 的观测数量: {missing_url_count:,}")
    if estimated_file_size_gb is None:
        print("- 估计总文件大小: 未找到 file_size_in_bytes 列")
    else:
        print(f"- 估计总文件大小: {estimated_file_size_gb:,.3f} GB")
    print(f"- pilot 样本数量: {len(pilot_sample):,}")


if __name__ == "__main__":
    main()
