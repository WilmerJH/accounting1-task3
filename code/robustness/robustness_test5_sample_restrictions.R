# robustness_test5_sample_restrictions_english.R
#
# Robustness Test #5: Sample Restrictions and Winsorization
#
# Local data sources:
#   data/generated/CAR/analysis_sample_car_m1_p1.csv
#   data/generated/tone/stratified_1500_lm_negtone_results.csv
#   data/generated/tone/full_10k_sample_dedup_stratified_1500_per_year.csv
#   data/external/10k_word_counts.csv
#   data/generated/regression/controls.csv
#
# Outputs:
#   output/robustness_test5_sample_restrictions.html

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(fixest)
  library(modelsummary)
})

# =============================================================================
# Project paths
# =============================================================================

# Run this script from the repository root
PROJECT_ROOT <- "."

dir.create(file.path(PROJECT_ROOT, "output"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(PROJECT_ROOT, "data/generated/regression"), recursive = TRUE, showWarnings = FALSE)

# =============================================================================
# Helper functions
# =============================================================================

clean_cik <- function(x) {
  x <- as.character(x)
  x <- trimws(x)
  x <- sub("\\.0$", "", x)
  x <- sub("^0+", "", x)
  x[x == ""] <- NA_character_
  x
}

winsorize <- function(x, lower = 0.01, upper = 0.99) {
  q <- quantile(x, probs = c(lower, upper), na.rm = TRUE)
  pmax(pmin(x, q[2]), q[1])
}

# =============================================================================
# Step 1: Load all data
# =============================================================================

# CAR data
car_data <- read_csv(
  file.path(PROJECT_ROOT, "data/generated/CAR/analysis_sample_car_m1_p1.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(
    cik = clean_cik(cik),
    fyear = as.integer(format(as.Date(report_date), "%Y"))
  ) %>%
  select(cik, fyear, car = car_vw_m1_p1)

# LM NegTone
# Do not filter parse_status == "success" strictly, because the local file may use
# a different parse_status label. The regression only needs non-missing negtone.
negtone_raw <- read_csv(
  file.path(PROJECT_ROOT, "data/generated/tone/stratified_1500_lm_negtone_results.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
)

cat("\n--- NegTone file diagnostics ---\n")
cat("Raw NegTone rows:", nrow(negtone_raw), "\n")
cat("NegTone columns:", paste(names(negtone_raw), collapse = ", "), "\n")

if ("parse_status" %in% names(negtone_raw)) {
  cat("parse_status distribution:\n")
  print(table(negtone_raw$parse_status, useNA = "ifany"))
}

negtone_data <- negtone_raw %>%
  mutate(
    cik = clean_cik(cik),
    fyear = as.integer(report_year)
  ) %>%
  filter(!is.na(negtone)) %>%
  select(cik, fyear, lm_negtone = negtone)

cat("Usable NegTone rows:", nrow(negtone_data), "\n")

# Control variables
controls <- read_csv(
  file.path(PROJECT_ROOT, "data/generated/regression/controls.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(
    cik = clean_cik(cik),
    fyear = as.integer(fyear)
  ) %>%
  select(cik, fyear, size, btm = bm, leverage, roa, loss, sic2)

# SIC codes from metadata
# SIC is stored as float in some files, e.g. 7374.0; convert to integer.
sic_data <- read_csv(
  file.path(PROJECT_ROOT, "data/generated/tone/full_10k_sample_dedup_stratified_1500_per_year.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(
    cik = clean_cik(cik),
    fyear = as.integer(report_year),
    sic = as.integer(sic)
  ) %>%
  distinct(cik, fyear, .keep_all = TRUE) %>%
  select(cik, fyear, sic)

# 10-K word counts
word_counts <- read_csv(
  file.path(PROJECT_ROOT, "data/external/10k_word_counts.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(
    cik = clean_cik(cik),
    fyear = as.integer(format(as.Date(report_date), "%Y"))
  ) %>%
  arrange(desc(word_count)) %>%
  distinct(cik, fyear, .keep_all = TRUE) %>%
  mutate(log_word_count = log(word_count)) %>%
  select(cik, fyear, log_word_count)

# =============================================================================
# Step 2: Merge all datasets
# =============================================================================

cat("\n--- Match diagnostics ---\n")
cat("car_data rows:     ", nrow(car_data), "\n")
cat("negtone_data rows: ", nrow(negtone_data), "\n")
cat("controls rows:     ", nrow(controls), "\n")
cat("sic_data rows:     ", nrow(sic_data), "\n")
cat("word_counts rows:  ", nrow(word_counts), "\n")

cat("CAR matched with NegTone: ",
    nrow(inner_join(car_data, negtone_data, by = c("cik", "fyear"))), "\n")

cat("CAR matched with controls: ",
    nrow(inner_join(car_data, controls, by = c("cik", "fyear"))), "\n")

cat("CAR matched with SIC data: ",
    nrow(inner_join(car_data, sic_data, by = c("cik", "fyear"))), "\n")

cat("CAR matched with word_counts: ",
    nrow(inner_join(car_data, word_counts, by = c("cik", "fyear"))), "\n")

merged_data <- car_data %>%
  left_join(negtone_data, by = c("cik", "fyear")) %>%
  left_join(controls,     by = c("cik", "fyear")) %>%
  left_join(sic_data,     by = c("cik", "fyear")) %>%
  left_join(word_counts,  by = c("cik", "fyear"))

cat("\n--- After merge ---\n")
cat("Merged sample size:", nrow(merged_data), "\n")
cat("Missing lm_negtone:", sum(is.na(merged_data$lm_negtone)), "\n")
cat("Missing size:      ", sum(is.na(merged_data$size)), "\n")
cat("Missing car:       ", sum(is.na(merged_data$car)), "\n")
cat("Missing sic:       ", sum(is.na(merged_data$sic)), "\n")
cat("Missing log words: ", sum(is.na(merged_data$log_word_count)), "\n")

reg_data <- merged_data %>%
  filter(!is.na(lm_negtone), !is.na(size), !is.na(car))

cat("\nFinal sample size:", nrow(reg_data), "\n")

if (nrow(reg_data) == 0) {
  stop("Regression sample is empty. Check CIK and fyear matching across input files.")
}

cat("Financial firms to be excluded (SIC 6000-6999):",
    sum(reg_data$sic >= 6000 & reg_data$sic <= 6999, na.rm = TRUE), "\n")

cat("Utilities to be excluded (SIC 4900-4999):",
    sum(reg_data$sic >= 4900 & reg_data$sic <= 4999, na.rm = TRUE), "\n")

# =============================================================================
# Step 3: Build three restricted samples
# =============================================================================

samples <- list(
  # (1) Baseline: full sample
  "Baseline" = reg_data,

  # (2) Exclude financial firms and utilities
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
print(sapply(samples, nrow))

# =============================================================================
# Step 4: Run regressions
# =============================================================================

cat("\nStarting regressions...\n")

models <- lapply(samples, function(data) {
  feols(
    car ~ lm_negtone + size + btm + leverage + roa + loss +
      log_word_count | sic2 + fyear,
    data = data,
    cluster = ~cik
  )
})

cat("Finished regressions. Writing HTML table...\n")

# =============================================================================
# Step 5: Output comparison table
# =============================================================================

modelsummary(
  models,
  coef_map = c("lm_negtone" = "LM NegTone"),
  title = "Robustness Test: Sample Restrictions and Winsorization",
  statistic = "({std.error})",
  gof_map = c("nobs", "r.squared"),
  stars = TRUE,
  notes = "Standard errors clustered at the firm level.
           All models include industry (2-digit SIC) and year fixed effects.
           Financial firms (SIC 6000-6999) and utilities (SIC 4900-4999)
           excluded in columns (2) and (3).
           Continuous variables winsorized at 1% and 99% in column (3).
           Exclusion of 10-K/A filings not applied due to
           unavailability of form type in the current dataset.
           past_ret and past_vol not included due to data unavailability.",
  output = file.path(PROJECT_ROOT, "output/robustness_test5_sample_restrictions.html")
)

cat("\nDone. Output written to output/robustness_test5_sample_restrictions.html\n")