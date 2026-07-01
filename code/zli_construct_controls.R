# ============================================================
# Z. Li part: Construct Compustat control variables
# Project: 10-K Negative Tone and Market Reaction
# Current plan: LM_NegTone only
# ============================================================

library(tidyverse)

# ------------------------------------------------------------
# Step 1: Read Compustat annual data
# 这一步：读取 Compustat 年度财务数据
#
# Required raw variables:
# gvkey, fyear, sic, at, ceq, ni, dltt, dlc, prcc_f, csho
# ------------------------------------------------------------

comp <- read_csv("data/external/compustat_annual.csv")

# 把所有列名转成小写，避免 WRDS 下载后大小写不一致
names(comp) <- tolower(names(comp))

# 看看文件里有哪些列
names(comp)


# ------------------------------------------------------------
# Step 2: Construct control variables
# 这一步：从 Compustat 原始财务变量生成回归控制变量
# ------------------------------------------------------------

controls <- comp %>%
  mutate(
    # 如果债务变量缺失，先当作 0 处理，避免 leverage 直接变成 NA
    dltt = replace_na(dltt, 0),
    dlc = replace_na(dlc, 0),

    # Market equity = fiscal-year-end price × common shares outstanding
    # 股票市值 = 年末股价 × 普通股股数
    market_equity = prcc_f * csho,

    # Firm size = log(total assets)
    # 公司规模 = 总资产取自然对数
    size = log(at),

    # Book-to-market = common equity / market equity
    # 账面市值比 = 普通股账面价值 / 股票市值
    bm = ceq / market_equity,

    # Leverage = total debt / total assets
    # 杠杆率 = 长期债务 + 短期债务，再除以总资产
    leverage = (dltt + dlc) / at,

    # ROA = net income / total assets
    # 盈利能力 = 净利润 / 总资产
    roa = ni / at,

    # Loss dummy = 1 if net income is negative, otherwise 0
    # 是否亏损：如果净利润小于 0，则为 1，否则为 0
    loss = if_else(ni < 0, 1, 0),

    # Two-digit SIC industry code
    # 二位数行业代码，用来做 industry fixed effects
    sic2 = floor(as.numeric(sic) / 100)
  ) %>%
  filter(
    at > 0,
    market_equity > 0
  ) %>%
  select(
    gvkey,
    fyear,
    sic,
    sic2,
    size,
    bm,
    leverage,
    roa,
    loss,
    market_equity
  )


# ------------------------------------------------------------
# Step 3: Check the controls dataset
# 这一步：检查生成的控制变量是否合理
# ------------------------------------------------------------

glimpse(controls)

controls %>%
  summarise(
    n_obs = n(),
    n_firms = n_distinct(gvkey),
    min_year = min(fyear, na.rm = TRUE),
    max_year = max(fyear, na.rm = TRUE),
    missing_size = sum(is.na(size)),
    missing_bm = sum(is.na(bm)),
    missing_leverage = sum(is.na(leverage)),
    missing_roa = sum(is.na(roa)),
    missing_loss = sum(is.na(loss))
  )


# ------------------------------------------------------------
# Step 4: Save controls
# 这一步：保存控制变量，后面主回归会直接读取这个文件
# ------------------------------------------------------------

dir.create("data/generated", recursive = TRUE, showWarnings = FALSE)

write_csv(controls, "data/generated/controls.csv")
