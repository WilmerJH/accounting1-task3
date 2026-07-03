# ============================================================
# Z. Li part: Main regression analysis
# Project: 10-K Negative Tone and Market Reaction
# Current plan: LM_NegTone only
# ============================================================

library(tidyverse)
library(fixest)
library(modelsummary)

# ------------------------------------------------------------
# Helper functions
# 这一步：统一 cik 和 gvkey 格式，避免合并时因为前导 0 或数字格式不同对不上
# ------------------------------------------------------------

clean_cik <- function(x) {
  x %>%
    as.character() %>%
    str_replace("\\.0$", "") %>%
    str_remove_all("[^0-9]") %>%
    na_if("") %>%
    str_pad(width = 10, pad = "0")
}

clean_gvkey <- function(x) {
  x %>%
    as.character() %>%
    str_replace("\\.0$", "") %>%
    str_remove_all("[^0-9]") %>%
    na_if("") %>%
    str_pad(width = 6, pad = "0")
}

# ------------------------------------------------------------
# Step 1: Read input files
# 这一步：读取 X、Y、controls 三份数据
# ------------------------------------------------------------

tone <- read_csv("data/generated/stratified_1500_lm_negtone_results.csv")
car <- read_csv("data/generated/10k_sample_with_car.csv")
controls <- read_csv("data/generated/controls.csv")

# ------------------------------------------------------------
# Step 2: Clean LM negative tone data
# 这一步：整理 X 变量，把 negtone 改名成 LM_NegTone
# ------------------------------------------------------------

tone_clean <- tone %>%
  mutate(
    cik = clean_cik(cik),
    filing_date = as.Date(filing_date),
    fyear = as.integer(report_year),
    LM_NegTone = negtone,
    text_length = total_words
  ) %>%
  filter(
    !is.na(LM_NegTone),
    !is.na(cik),
    !is.na(filing_date)
  ) %>%
  select(
    cik,
    filing_date,
    fyear,
    accession_number,
    LM_NegTone,
    text_length,
    negative_words,
    section_used,
    status
  ) %>%
  distinct(cik, filing_date, accession_number, .keep_all = TRUE)

# ------------------------------------------------------------
# Step 3: Clean CAR data
# 这一步：整理 Y 变量，把 car_vw_m1_p1 改名成 CAR_m1_p1
# ------------------------------------------------------------

car_clean <- car %>%
  mutate(
    cik = clean_cik(cik),
    gvkey = clean_gvkey(gvkey),
    filing_date = as.Date(filing_date),
    event_date = as.Date(event_date),
    CAR_m1_p1 = car_vw_m1_p1
  ) %>%
  filter(
    !is.na(CAR_m1_p1),
    !is.na(cik),
    !is.na(filing_date),
    !is.na(gvkey)
  ) %>%
  select(
    cik,
    gvkey,
    permno,
    filing_date,
    event_date,
    CAR_m1_p1,
    car_vw_0_p1,
    car_vw_m2_p2,
    car_ew_0_p1,
    car_ew_m1_p1,
    car_ew_m2_p2
  ) %>%
  distinct(cik, gvkey, filing_date, permno, .keep_all = TRUE)

# ------------------------------------------------------------
# Step 4: Clean control variables
# 这一步：整理 controls，确保 gvkey 和 fyear 格式一致
# ------------------------------------------------------------

controls_clean <- controls %>%
  mutate(
    gvkey = clean_gvkey(gvkey),
    fyear = as.integer(fyear)
  ) %>%
  distinct(gvkey, fyear, .keep_all = TRUE)

# ------------------------------------------------------------
# Step 5: Merge LM_NegTone and CAR
# 这一步：用 cik + filing_date 把 X 和 Y 合并
# ------------------------------------------------------------

sample_xy <- car_clean %>%
  inner_join(
    tone_clean,
    by = c("cik", "filing_date")
  )

# ------------------------------------------------------------
# Step 6: Merge controls
# 这一步：用 gvkey + fyear 把 Compustat 控制变量合并进来
# ------------------------------------------------------------

main_sample <- sample_xy %>%
  left_join(
    controls_clean,
    by = c("gvkey", "fyear")
  )

# ------------------------------------------------------------
# Step 7: Check merged sample
# 这一步：检查合并后样本数量、缺失值和重复值
# ------------------------------------------------------------

main_sample_summary <- main_sample %>%
  summarise(
    n_obs = n(),
    n_firms = n_distinct(gvkey),
    min_year = min(fyear, na.rm = TRUE),
    max_year = max(fyear, na.rm = TRUE),
    duplicate_firm_years = sum(duplicated(paste(gvkey, fyear))),
    missing_car = sum(is.na(CAR_m1_p1)),
    missing_tone = sum(is.na(LM_NegTone)),
    missing_size = sum(is.na(size)),
    missing_bm = sum(is.na(bm)),
    missing_leverage = sum(is.na(leverage)),
    missing_roa = sum(is.na(roa)),
    missing_loss = sum(is.na(loss)),
    missing_text_length = sum(is.na(text_length))
  )

print(main_sample_summary)

# ------------------------------------------------------------
# Step 8: Create regression sample
# 这一步：删除主回归变量缺失的 observations
# ------------------------------------------------------------

reg_sample <- main_sample %>%
  drop_na(
    CAR_m1_p1,
    LM_NegTone,
    size,
    bm,
    leverage,
    roa,
    loss,
    text_length,
    sic2,
    fyear
  )

reg_sample_summary <- reg_sample %>%
  summarise(
    n_obs = n(),
    n_firms = n_distinct(gvkey),
    min_year = min(fyear, na.rm = TRUE),
    max_year = max(fyear, na.rm = TRUE)
  )

print(reg_sample_summary)

# ------------------------------------------------------------
# Step 9: Run baseline regressions
# 这一步：只用 LM_NegTone 做主回归，不再做 LLM 对比
# ------------------------------------------------------------

m1 <- feols(
  CAR_m1_p1 ~ LM_NegTone,
  data = reg_sample,
  cluster = ~ gvkey
)

m2 <- feols(
  CAR_m1_p1 ~ LM_NegTone + size + bm + leverage + roa + loss + text_length,
  data = reg_sample,
  cluster = ~ gvkey
)

m3 <- feols(
  CAR_m1_p1 ~ LM_NegTone + size + bm + leverage + roa + loss + text_length |
    fyear + sic2,
  data = reg_sample,
  cluster = ~ gvkey
)

# ------------------------------------------------------------
# Step 10: Export regression table and final sample
# 这一步：输出主回归表和最终回归样本
# ------------------------------------------------------------

dir.create("output/tables", recursive = TRUE, showWarnings = FALSE)

modelsummary(
  list(
    "Tone only" = m1,
    "With controls" = m2,
    "Controls + FE" = m3
  ),
  stars = TRUE,
  output = "output/tables/main_regression.html"
)

write_csv(reg_sample, "data/generated/main_regression_sample.csv")