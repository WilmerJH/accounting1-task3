"""
从 2002-2024 初始 10-K 样本中创建 pilot 样本。

本脚本读取 data/generated/initial_10k_sample_2002_2024.csv，
并输出 data/generated/pilot_10k_sample_500.csv。
"""

import sys
from pathlib import Path

import pandas as pd


# Windows 终端有时会使用非 UTF-8 编码；这里尽量保证中文进度信息正常显示。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# -----------------------------
# 路径和抽样参数设置
# -----------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "data" / "generated"

INITIAL_SAMPLE_FILE = OUTPUT_DIR / "initial_10k_sample_2002_2024.csv"
PILOT_SAMPLE_FILE = OUTPUT_DIR / "pilot_10k_sample_500.csv"

PILOT_SAMPLE_SIZE = 500
RANDOM_STATE = 123


def require_columns(df: pd.DataFrame, required_columns: list[str]) -> None:
    """检查必要列是否存在；如果缺失，给出清楚的错误信息。"""
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(
            "初始样本缺少必要列: "
            + ", ".join(missing_columns)
            + f"\n请先检查或重新生成文件: {INITIAL_SAMPLE_FILE}"
        )


def main() -> None:
    print("开始创建 10-K pilot 样本...")

    if not INITIAL_SAMPLE_FILE.exists():
        raise FileNotFoundError(
            "找不到初始样本文件，请先运行描述性统计脚本:\n"
            f"{INITIAL_SAMPLE_FILE}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"正在读取初始样本: {INITIAL_SAMPLE_FILE}")
    sample = pd.read_csv(INITIAL_SAMPLE_FILE, dtype={"cik": "string"}, low_memory=False)
    print(f"初始样本读取完成，共 {len(sample):,} 条记录。")

    require_columns(sample, ["cik", "report_year"])

    # 如果可用样本少于 500 条，则保留全部；否则使用固定随机种子抽样。
    pilot_n = min(PILOT_SAMPLE_SIZE, len(sample))
    print(f"正在生成 pilot 样本，目标样本量为 {pilot_n:,} 条...")

    if pilot_n < len(sample):
        pilot_sample = sample.sample(n=pilot_n, random_state=RANDOM_STATE)
    else:
        pilot_sample = sample.copy()

    print(f"正在保存 pilot 样本: {PILOT_SAMPLE_FILE}")
    pilot_sample.to_csv(PILOT_SAMPLE_FILE, index=False)

    print("\npilot 样本创建完成。")
    print("输出文件路径:")
    print(f"- pilot 样本: {PILOT_SAMPLE_FILE}")
    print("\n主要样本量汇总:")
    print(f"- 初始样本数量: {len(sample):,}")
    print(f"- pilot 样本数量: {len(pilot_sample):,}")
    print(f"- 随机种子 random_state: {RANDOM_STATE}")


if __name__ == "__main__":
    main()
