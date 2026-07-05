# robustness_test1_event_windows.R
#
# Robustness Test #1: Alternative Event Windows [0,+1] and [-2,+2]
#
# Local data sources:
#   data/generated/CAR/analysis_sample_car_m1_p1.csv
#   data/generated/tone/stratified_1500_lm_negtone_results.csv
#   data/generated/regression/controls.csv
#   data/external/10k_word_counts.csv

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(fixest)
  library(modelsummary)
})

# Project root: run this script from the repository root
PROJECT_ROOT <- "."

dir.create(file.path(PROJECT_ROOT, "output"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(PROJECT_ROOT, "data/generated/regression"), recursive = TRUE, showWarnings = FALSE)

# =============================================================================
# Step 1: Load all data
# =============================================================================

# CAR data
# Contains pre-computed CAR for three event windows
car_data <- read_csv(
  file.path(PROJECT_ROOT, "data/generated/CAR/analysis_sample_car_m1_p1.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(fyear = as.integer(format(as.Date(report_date), "%Y"))) %>%
  select(cik, fyear,
         car_m1_p1 = car_vw_m1_p1,   # Main regression window [-1,+1]
         car_0_p1  = car_vw_0_p1,    # Robustness window [0,+1]
         car_m2_p2 = car_vw_m2_p2)   # Robustness window [-2,+2]

# LM NegTone
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
    parse_status_clean = if ("parse_status" %in% names(.)) {
      tolower(trimws(as.character(parse_status)))
    } else {
      NA_character_
    }
  ) %>%
  filter(!is.na(negtone)) %>%
  select(cik, fyear = report_year, lm_negtone = negtone)

cat("Usable NegTone rows:", nrow(negtone_data), "\n")

# Control variables
controls <- read_csv(
  file.path(PROJECT_ROOT, "data/generated/regression/controls.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  select(cik, fyear, size, btm = bm, leverage, roa, loss, sic2)

# 10-K word counts
# Keep the largest word count per firm-year to avoid duplicates
word_counts <- read_csv(
  file.path(PROJECT_ROOT, "data/external/10k_word_counts.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(fyear = as.integer(format(as.Date(report_date), "%Y"))) %>%
  arrange(desc(word_count)) %>%
  distinct(cik, fyear, .keep_all = TRUE) %>%
  mutate(log_word_count = log(word_count)) %>%
  select(cik, fyear, log_word_count)

# =============================================================================
# Step 2: Harmonize merge keys and merge all datasets
# =============================================================================

clean_cik <- function(x) {
  x <- as.character(x)
  x <- trimws(x)
  x <- sub("\\.0$", "", x)
  x <- sub("^0+", "", x)
  x[x == ""] <- NA_character_
  x
}

car_data <- car_data %>%
  mutate(
    cik = clean_cik(cik),
    fyear = as.integer(fyear)
  )

negtone_data <- negtone_data %>%
  mutate(
    cik = clean_cik(cik),
    fyear = as.integer(fyear)
  )

controls <- controls %>%
  mutate(
    cik = clean_cik(cik),
    fyear = as.integer(fyear)
  )

word_counts <- word_counts %>%
  mutate(
    cik = clean_cik(cik),
    fyear = as.integer(fyear)
  )

cat("\n--- Match diagnostics ---\n")
cat("car_data rows:     ", nrow(car_data), "\n")
cat("negtone_data rows: ", nrow(negtone_data), "\n")
cat("controls rows:     ", nrow(controls), "\n")
cat("word_counts rows:  ", nrow(word_counts), "\n")

cat("CAR matched with NegTone: ",
    nrow(inner_join(car_data, negtone_data, by = c("cik", "fyear"))), "\n")

cat("CAR matched with controls: ",
    nrow(inner_join(car_data, controls, by = c("cik", "fyear"))), "\n")

cat("CAR matched with word_counts: ",
    nrow(inner_join(car_data, word_counts, by = c("cik", "fyear"))), "\n")

merged_data <- car_data %>%
  left_join(negtone_data, by = c("cik", "fyear")) %>%
  left_join(controls,     by = c("cik", "fyear")) %>%
  left_join(word_counts,  by = c("cik", "fyear"))

cat("\n--- After merge ---\n")
cat("Merged sample size:", nrow(merged_data), "\n")
cat("Missing lm_negtone:", sum(is.na(merged_data$lm_negtone)), "\n")
cat("Missing size:      ", sum(is.na(merged_data$size)), "\n")
cat("Missing car_m1_p1: ", sum(is.na(merged_data$car_m1_p1)), "\n")
cat("Missing log words: ", sum(is.na(merged_data$log_word_count)), "\n")

reg_data <- merged_data %>%
  filter(!is.na(lm_negtone), !is.na(size), !is.na(car_m1_p1))

cat("Final regression sample size:", nrow(reg_data), "\n")

if (nrow(reg_data) == 0) {
  stop("Regression sample is empty. Check CIK and fyear matching across input files.")
}

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
               past_ret and past_vol not included due to data unavailability.",
  output    = file.path(PROJECT_ROOT, "output/robustness_test1_event_windows.html")
)
