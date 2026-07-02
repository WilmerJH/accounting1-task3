# robustness_test1_event_windows.R
#
# Robustness Test #1: Alternative Event Windows [0,+1] and [-2,+2]
#
# Data sources (files located in different branches):
#   main   / data/generated/analysis_sample_car_m1_p1.csv              -> CAR data (C. Han)
#   main   / data/external/10k_word_counts.csv                         -> 10-K word counts
#   Lingke / Negtone_data/stratified_1500_lm_negtone_results.csv       -> LM NegTone (L. Zhang)
#   Zilong / data/generated/controls.csv                               -> Control variables (Z. Li)

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(fixest)
  library(modelsummary)
})

# Raw URL base paths for each branch
RAW_MAIN   <- "https://raw.githubusercontent.com/WilmerJH/accounting1-task3/main"
RAW_LINGKE <- "https://raw.githubusercontent.com/WilmerJH/accounting1-task3/Lingke"
RAW_ZILONG <- "https://raw.githubusercontent.com/WilmerJH/accounting1-task3/Zilong"

# =============================================================================
# Step 1: Load all data
# =============================================================================

# CAR data from C. Han (main branch)
# Contains pre-computed CAR for three event windows
car_data <- read_csv(
  paste0(RAW_MAIN, "/data/generated/analysis_sample_car_m1_p1.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(fyear = as.integer(format(as.Date(report_date), "%Y"))) %>%
  select(cik, fyear,
         car_m1_p1 = car_vw_m1_p1,   # Main regression window [-1,+1]
         car_0_p1  = car_vw_0_p1,    # Robustness window [0,+1]
         car_m2_p2 = car_vw_m2_p2)   # Robustness window [-2,+2]

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
  left_join(word_counts,  by = c("cik", "fyear")) %>%
  filter(!is.na(lm_negtone), !is.na(size), !is.na(car_m1_p1))

cat("Final sample size:", nrow(reg_data), "\n")

# =============================================================================
# Step 3: Run regressions (only the CAR window changes across models)
# =============================================================================

models <- list(
  "CAR[-1,+1]" = feols(car_m1_p1 ~ lm_negtone + size + btm + leverage +
                          roa + loss + log_word_count | sic2 + fyear,
                        data = reg_data, cluster = ~cik),
  "CAR[0,+1]"  = feols(car_0_p1  ~ lm_negtone + size + btm + leverage +
                          roa + loss + log_word_count | sic2 + fyear,
                        data = reg_data, cluster = ~cik),
  "CAR[-2,+2]" = feols(car_m2_p2 ~ lm_negtone + size + btm + leverage +
                          roa + loss + log_word_count | sic2 + fyear,
                        data = reg_data, cluster = ~cik)
)

# =============================================================================
# Step 4: Output comparison table
# =============================================================================

modelsummary(
  models,
  coef_map  = c("lm_negtone" = "LM NegTone"),
  title     = "Robustness Test: Alternative Event Windows",
  statistic = "({std.error})",
  gof_map   = c("nobs", "r.squared"),
  stars     = TRUE,
  notes     = "Standard errors clustered at the firm level.
               All models include industry (2-digit SIC) and year fixed effects.
               Column (1) reproduces the main result with CAR[-1,+1].
               past_ret and past_vol not included due to data unavailability."
)
