# ============================================================
# Z. Li part: Construct Compustat control variables
# Project: 10-K Negative Tone and Market Reaction
# Current plan: LM_NegTone only
# ============================================================

library(tidyverse)

# ------------------------------------------------------------
# Step 1: Read Compustat annual data
# 这一步：读取从 WRDS 下载的 Compustat 年度财务数据
# 注意：这个原始数据不要上传到 public GitHub
# ------------------------------------------------------------

comp <- read_csv("data/external/compustat_annual.csv")

# 把列名统一成小写，避免大小写问题
names(comp) <- tolower(names(comp))


# ------------------------------------------------------------
# Step 2: Clean identifiers and remove duplicate firm-years
# 这一步：整理公司 ID，并确保每个 gvkey-fyear 只保留一行
# ------------------------------------------------------------

comp_clean <- comp %>%
  mutate(
    gvkey = str_pad(as.character(gvkey), width = 6, pad = "0"),

    cik = as.character(cik),
    cik = str_replace(cik, "\\.0$", ""),
    cik = if_else(is.na(cik) | cik == "NA", NA_character_, str_pad(cik, width = 10, pad = "0")),

    # 如果同一个 firm-year 同时有 INDL 和 FS，优先保留 INDL
    indfmt_priority = case_when(
      indfmt == "INDL" ~ 1,
      indfmt == "FS" ~ 2,
      TRUE ~ 3
    )
  ) %>%
  arrange(
    gvkey,
    fyear,
    indfmt_priority
  ) %>%
  group_by(gvkey, fyear) %>%
  slice(1) %>%
  ungroup()


# ------------------------------------------------------------
# Step 3: Construct control variables
# 这一步：从 Compustat 原始变量生成回归需要的控制变量
# ------------------------------------------------------------

controls <- comp_clean %>%
  mutate(
    # 如果债务变量缺失，先当作 0 处理
    dltt = replace_na(dltt, 0),
    dlc = replace_na(dlc, 0),

    # Market equity = fiscal-year-end price × common shares outstanding
    # 股票市值 = 年末股价 × 普通股股数
    market_equity = prcc_f * csho,

    # Firm size = log(total assets)
    # 公司规模 = 总资产取自然对数
    size = log(at),

    # Book-to-market = common equity / market equity
    # 账面市值比 = 普通股权益 / 股票市值
    bm = ceq / market_equity,

    # Leverage = total debt / total assets
    # 杠杆率 = 长期债务 + 短期债务，再除以总资产
    leverage = (dltt + dlc) / at,

    # ROA = net income / total assets
    # 盈利能力 = 净利润 / 总资产
    roa = ni / at,

    # Loss dummy = 1 if net income is negative, otherwise 0
    # 是否亏损：净利润小于 0 时为 1，否则为 0
    loss = if_else(ni < 0, 1, 0),

    # Two-digit SIC industry code
    # 二位数行业代码，用于 industry fixed effects
    sic2 = floor(as.numeric(sic) / 100)
  ) %>%
  filter(
    at > 0,
    market_equity > 0,
    fyear >= 2001,
    fyear <= 2024
  ) %>%
  select(
    gvkey,
    fyear,
    costat,
    indfmt,
    conm,
    tic,
    cusip,
    cik,
    sic,
    sic2,
    size,
    bm,
    leverage,
    roa,
    loss,
    market_equity,
    at,
    ceq,
    dlc,
    dltt,
    ni,
    csho,
    prcc_f
  )


# ------------------------------------------------------------
# Step 4: Check the controls dataset
# 这一步：检查生成的控制变量是否合理
# ------------------------------------------------------------

glimpse(controls)

controls %>%
  summarise(
    n_obs = n(),
    n_firms = n_distinct(gvkey),
    min_year = min(fyear, na.rm = TRUE),
    max_year = max(fyear, na.rm = TRUE),
    duplicate_firm_years = sum(duplicated(paste(gvkey, fyear))),
    missing_size = sum(is.na(size)),
    missing_bm = sum(is.na(bm)),
    missing_leverage = sum(is.na(leverage)),
    missing_roa = sum(is.na(roa)),
    missing_loss = sum(is.na(loss))
  )


# ------------------------------------------------------------
# Step 5: Save controls
# 这一步：保存控制变量，后面主回归会直接读取这个文件
# ------------------------------------------------------------

dir.create("data/generated", recursive = TRUE, showWarnings = FALSE)

write_csv(controls, "data/generated/controls.csv")
