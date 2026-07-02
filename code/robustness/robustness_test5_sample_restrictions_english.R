# robustness_test5_sample_restrictions.R
#
# Robustness Test #5: Sample Restrictions and Winsorization
#
# Data sources (files located in different branches):
#   main   / data/generated/analysis_sample_car_m1_p1.csv                        -> CAR data (C. Han)
#   main   / data/generated/full_10k_sample_dedup_stratified_1500_per_year.csv   -> SIC codes
#   main   / data/external/10k_word_counts.csv                                   -> 10-K word counts
#   Lingke / Negtone_data/stratified_1500_lm_negtone_results.csv                 -> LM NegTone (L. Zhang)
#   Zilong / data/generated/controls.csv                                          -> Control variables (Z. Li)
#
# Notes:
#   - form_type column is unavailable; exclusion of 10-K/A filings is not applied (see table notes)
#   - SIC codes are stored as floats (e.g. 7374.0); converted to integer before filtering

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(fixest)
  library(modelsummary)
})

RAW_MAIN   <- "https://raw.githubusercontent.com/WilmerJH/accounting1-task3/main"
RAW_LINGKE <- "https://raw.githubusercontent.com/WilmerJH/accounting1-task3/Lingke"
RAW_ZILONG <- "https://raw.githubusercontent.com/WilmerJH/accounting1-task3/Zilong"

# =============================================================================
# Step 1: Load all data
# =============================================================================

# CAR data from C. Han (main branch)
car_data <- read_csv(
  paste0(RAW_MAIN, "/data/generated/analysis_sample_car_m1_p1.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(fyear = as.integer(format(as.Date(report_date), "%Y"))) %>%
  select(cik, fyear, car = car_vw_m1_p1)

# LM NegTone from L. Zhang (Lingke branch)
negtone_data <- read_csv(
  paste0(RAW_LINGKE, "/Negtone_data/stratified_1500_lm_negtone_results.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  filter(parse_status == "success") %>%
  select(cik, fyear = report_year, lm_negtone = negtone)

# Control variables from Z. Li (Zilong branch)
controls <- read_csv(
  paste0(RAW_ZILONG, "/data/generated/controls.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  select(cik, fyear, size, btm = bm, leverage, roa, loss, sic2)

# SIC codes from metadata (main branch)
# SIC is stored as float (7374.0); convert to integer for range filtering
sic_data <- read_csv(
  paste0(RAW_MAIN, "/data/generated/full_10k_sample_dedup_stratified_1500_per_year.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(
    fyear = as.integer(report_year),
    sic   = as.integer(sic)
  ) %>%
  distinct(cik, fyear, .keep_all = TRUE) %>%
  select(cik, fyear, sic)

# 10-K word counts (main branch)
# Keep the largest word count per firm-year to avoid duplicates
word_counts <- read_csv(
  paste0(RAW_MAIN, "/data/external/10k_word_counts.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(fyear = as.integer(format(as.Date(report_date), "%Y"))) %>%
  arrange(desc(word_count)) %>%
  distinct(cik, fyear, .keep_all = TRUE) %>%
  mutate(log_word_count = log(word_count)) %>%
  select(cik, fyear, log_word_count)

# =============================================================================
# Step 2: Merge all datasets
# =============================================================================

reg_data <- car_data %>%
  left_join(negtone_data, by = c("cik", "fyear")) %>%
  left_join(controls,     by = c("cik", "fyear")) %>%
  left_join(sic_data,     by = c("cik", "fyear")) %>%
  left_join(word_counts,  by = c("cik", "fyear")) %>%
  filter(!is.na(lm_negtone), !is.na(size), !is.na(car))

cat("Final sample size:", nrow(reg_data), "\n")
cat("Financial firms to be excluded (SIC 6000-6999):",
    sum(reg_data$sic >= 6000 & reg_data$sic <= 6999, na.rm = TRUE), "\n")
cat("Utilities to be excluded (SIC 4900-4999):",
    sum(reg_data$sic >= 4900 & reg_data$sic <= 4999, na.rm = TRUE), "\n")

# =============================================================================
# Step 3: Winsorize function
# =============================================================================

# Replaces values below the lower quantile or above the upper quantile
# with the respective quantile boundary (default: 1% and 99%)
winsorize <- function(x, lower = 0.01, upper = 0.99) {
  q <- quantile(x, probs = c(lower, upper), na.rm = TRUE)
  pmax(pmin(x, q[2]), q[1])
}

# =============================================================================
# Step 4: Build three restricted samples
# =============================================================================

samples <- list(
  # (1) Baseline: full sample
  "Baseline" = reg_data,

  # (2) Exclude financial firms (SIC 6000-6999) and utilities (SIC 4900-4999)
  "Excl. Fin. & Util." = reg_data %>%
    filter(
      !(sic >= 6000 & sic <= 6999),
      !(sic >= 4900 & sic <= 4999)
    ),

  # (3) Same exclusions + winsorize all continuous variables at 1%/99%
  "Excl. Fin. & Util.\n+ Winsorize" = reg_data %>%
    filter(
      !(sic >= 6000 & sic <= 6999),
      !(sic >= 4900 & sic <= 4999)
    ) %>%
    mutate(across(
      c(car, lm_negtone, size, btm, leverage, roa, log_word_count),
      winsorize
    ))
)

cat("\nSample sizes per restriction:\n")
sapply(samples, nrow) %>% print()

# =============================================================================
# Step 5: Run regressions
# =============================================================================

models <- lapply(samples, function(data) {
  feols(car ~ lm_negtone + size + btm + leverage + roa + loss +
          log_word_count | sic2 + fyear,
        data = data, cluster = ~cik)
})

# =============================================================================
# Step 6: Output comparison table
# =============================================================================

modelsummary(
  models,
  coef_map  = c("lm_negtone" = "LM NegTone"),
  title     = "Robustness Test: Sample Restrictions and Winsorization",
  statistic = "({std.error})",
  gof_map   = c("nobs", "r.squared"),
  stars     = TRUE,
  notes     = "Standard errors clustered at the firm level.
               All models include industry (2-digit SIC) and year fixed effects.
               Financial firms (SIC 6000-6999) and utilities (SIC 4900-4999)
               excluded in columns (2) and (3).
               Continuous variables winsorized at 1% and 99% in column (3).
               Exclusion of 10-K/A filings not applied due to
               unavailability of form type in the current dataset.
               past_ret and past_vol not included due to data unavailability."
)
