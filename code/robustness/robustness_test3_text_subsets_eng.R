# robustness_test3_text_subsets.R
#
# Robustness Test #3: NegTone Constructed from Different Text Subsets
# (Part I only / Part II only / Item 1A Risk Factors only)
#
# Data sources (files located in different branches):
#   main   / data/generated/analysis_sample_car_m1_p1.csv                    -> CAR data (C. Han)
#   main   / data/generated/full_10k_sample_dedup_stratified_1500_per_year.csv -> Filing metadata (URL, year)
#   main   / data/external/10k_word_counts.csv                               -> 10-K word counts
#   Lingke / data/external/Loughran-McDonald_MasterDictionary_1993-2025.csv  -> LM dictionary
#   Zilong / data/generated/controls.csv                                     -> Control variables (Z. Li)
#   SEC EDGAR (via URL column in metadata)                                   -> 10-K full text (downloaded at runtime)
#
# Sampling strategy:
#   Stratified sample of ~87 filings per year across 23 years (2002-2024),
#   yielding ~2,001 filings total. This matches the 1,500/year stratification
#   logic used in the main regression sample.
#
# Estimated runtime: ~50 minutes (2,000 filings x ~1.5 seconds each)

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(stringr)
  library(fixest)
  library(modelsummary)
  library(httr)
  library(rvest)
})

RAW_MAIN   <- "https://raw.githubusercontent.com/WilmerJH/accounting1-task3/main"
RAW_LINGKE <- "https://raw.githubusercontent.com/WilmerJH/accounting1-task3/Lingke"
RAW_ZILONG <- "https://raw.githubusercontent.com/WilmerJH/accounting1-task3/Zilong"

# Your name and email are required by SEC EDGAR for automated downloads
# Replace with your actual information
SEC_USER_AGENT <- "Yi Yang yi.yang.kuo@student.hu-berlin.de"

# Random seed for reproducibility of stratified sample
RANDOM_SEED  <- 123
N_PER_YEAR   <- 87   # 87 filings x 23 years = ~2,001 total

# =============================================================================
# Step 1: Load CAR, controls, and word counts
# =============================================================================

# CAR data from C. Han (main branch)
car_data <- read_csv(
  paste0(RAW_MAIN, "/data/generated/analysis_sample_car_m1_p1.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(fyear = as.integer(format(as.Date(report_date), "%Y"))) %>%
  select(cik, fyear, car = car_vw_m1_p1)

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
# Step 2: Load LM negative word dictionary (Lingke branch)
# =============================================================================

neg_words <- read_csv(
  paste0(RAW_LINGKE, "/data/external/Loughran-McDonald_MasterDictionary_1993-2025.csv"),
  show_col_types = FALSE
) %>%
  { tolower(.$Word[.$Negative != 0]) }

cat("Number of LM negative words:", length(neg_words), "\n")

# =============================================================================
# Step 3: Draw stratified sample from the 34,500-filing metadata
# =============================================================================

# Read full metadata (main branch) - contains URL and report_year for all filings
meta_full <- read_csv(
  paste0(RAW_MAIN, "/data/generated/full_10k_sample_dedup_stratified_1500_per_year.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
)

# Stratified sample: N_PER_YEAR filings per year, keeping year distribution even
set.seed(RANDOM_SEED)
meta_sample <- meta_full %>%
  filter(!is.na(url), download_success == TRUE) %>%
  group_by(report_year) %>%
  slice_sample(n = N_PER_YEAR) %>%
  ungroup() %>%
  mutate(fyear = as.integer(report_year)) %>%
  select(cik, fyear, url)

cat("Stratified sample size:", nrow(meta_sample), "filings\n")
cat("Year distribution:\n")
print(table(meta_sample$fyear))

# =============================================================================
# Step 4: Core functions for section extraction and NegTone computation
# =============================================================================

# Find the position of the last true section header for a given Item label.
# Strategy: locate all occurrences of "Item X", then exclude those followed
# by a quotation mark within 60 characters (those are inline references,
# not actual section headers). Take the last remaining occurrence.
find_section_header <- function(text, item_label) {
  pattern <- regex(paste0("item\\s*", item_label, "(?=[.:\\s])"), ignore_case = TRUE)
  pos_mat  <- str_locate_all(text, pattern)[[1]]
  if (nrow(pos_mat) == 0) return(NA_integer_)
  starts <- pos_mat[, "start"]
  is_ref <- vapply(starts, function(s) {
    snippet <- str_sub(text, s, min(s + 60, nchar(text)))
    str_detect(snippet, '[\\"\\u201c\\u201d]')
  }, logical(1))
  real <- starts[!is_ref]
  if (length(real) == 0) return(NA_integer_)
  real[length(real)]
}

# Extract the text between two Item section headers
extract_item <- function(text, start_label, end_label) {
  s <- find_section_header(text, start_label)
  e <- find_section_header(text, end_label)
  if (is.na(s)) return(NA_character_)
  end_pos <- if (is.na(e) || e <= s) nchar(text) else e - 1
  str_trim(str_sub(text, s, end_pos))
}

# Compute LM NegTone: number of negative words / total words
compute_lm_negtone <- function(text, neg_words) {
  if (is.na(text) || nchar(text) == 0) return(NA_real_)
  words <- str_extract_all(tolower(text), "[a-z]+")[[1]]
  if (length(words) == 0) return(NA_real_)
  sum(words %in% neg_words) / length(words)
}

# =============================================================================
# Step 5: Download from SEC EDGAR and compute NegTone for each filing
# =============================================================================

# Download one 10-K filing from SEC EDGAR and compute NegTone for three sections
process_one_filing <- function(url, neg_words, user_agent) {
  raw <- tryCatch({
    resp <- GET(url,
                user_agent(user_agent),  # SEC requires a valid User-Agent
                timeout(60))
    if (http_error(resp)) return(NULL)
    content(resp, as = "text", encoding = "UTF-8")
  }, error = function(e) NULL)

  if (is.null(raw)) return(NULL)

  # Convert HTML to plain text if needed
  if (str_detect(raw, "<html|<HTML|<!DOCTYPE")) {
    page <- tryCatch(read_html(raw), error = function(e) NULL)
    if (!is.null(page)) raw <- html_text2(page)
  }

  list(
    part1_negtone  = compute_lm_negtone(extract_item(raw, "1",  "5"),  neg_words),
    part2_negtone  = compute_lm_negtone(extract_item(raw, "5",  "10"), neg_words),
    item1a_negtone = compute_lm_negtone(extract_item(raw, "1A", "1B"), neg_words)
  )
}

# Batch process all sampled filings
build_negtone_subsets <- function(meta_sample, neg_words, user_agent,
                                   sleep_sec = 0.3) {
  n   <- nrow(meta_sample)
  out <- vector("list", n)

  for (i in seq_len(n)) {
    result <- tryCatch(
      process_one_filing(meta_sample$url[i], neg_words, user_agent),
      error = function(e) NULL
    )
    out[[i]] <- tibble(
      cik            = meta_sample$cik[i],
      fyear          = meta_sample$fyear[i],
      part1_negtone  = if (is.null(result)) NA_real_ else result$part1_negtone,
      part2_negtone  = if (is.null(result)) NA_real_ else result$part2_negtone,
      item1a_negtone = if (is.null(result)) NA_real_ else result$item1a_negtone,
      download_ok    = !is.null(result)
    )

    Sys.sleep(sleep_sec)  # Respect SEC EDGAR rate limit — do not remove

    if (i %% 100 == 0 || i == n)
      cat(sprintf("  Progress: %d / %d  (successful: %d)\n",
                  i, n, sum(sapply(out[1:i], function(x) x$download_ok))))
  }
  bind_rows(out)
}

# =============================================================================
# Step 6: Execute download and NegTone computation
# =============================================================================

cat("\nDownloading", nrow(meta_sample), "filings from SEC EDGAR...\n")
cat("Estimated runtime: ~50 minutes\n\n")

negtone_subsets <- build_negtone_subsets(meta_sample, neg_words, SEC_USER_AGENT)

# Summary of download and parsing results
cat("\nDownload success rate:",
    sum(negtone_subsets$download_ok), "/", nrow(negtone_subsets), "\n")

cat("\nDescriptive statistics for NegTone subsets:\n")
negtone_subsets %>%
  filter(download_ok) %>%
  summarise(across(ends_with("_negtone"),
                   list(mean = ~mean(., na.rm = TRUE),
                        n_na = ~sum(is.na(.))))) %>%
  print()

# =============================================================================
# Step 7: Merge and run regressions
# =============================================================================

reg_data <- car_data %>%
  left_join(negtone_subsets %>% filter(download_ok),
            by = c("cik", "fyear")) %>%
  left_join(controls,   by = c("cik", "fyear")) %>%
  left_join(word_counts, by = c("cik", "fyear")) %>%
  filter(!is.na(size), !is.na(car))

cat("\nFinal regression sample size:", nrow(reg_data), "\n")

models <- list(
  "Part I"  = feols(car ~ part1_negtone  + size + btm + leverage + roa +
                      loss + log_word_count | sic2 + fyear,
                    data = reg_data, cluster = ~cik),
  "Part II" = feols(car ~ part2_negtone  + size + btm + leverage + roa +
                      loss + log_word_count | sic2 + fyear,
                    data = reg_data, cluster = ~cik),
  "Item 1A" = feols(car ~ item1a_negtone + size + btm + leverage + roa +
                      loss + log_word_count | sic2 + fyear,
                    data = reg_data, cluster = ~cik)
)

# =============================================================================
# Step 8: Output comparison table
# =============================================================================

modelsummary(
  models,
  coef_map  = c(
    "part1_negtone"  = "LM NegTone",
    "part2_negtone"  = "LM NegTone",
    "item1a_negtone" = "LM NegTone"
  ),
  title     = "Robustness Test: NegTone from Different Text Subsets",
  statistic = "({std.error})",
  gof_map   = c("nobs", "r.squared"),
  stars     = TRUE,
  notes     = "Standard errors clustered at the firm level.
               All models include industry (2-digit SIC) and year fixed effects.
               Based on a stratified random sample of ~87 filings per year (2002-2024),
               yielding ~2,001 filings total. Seed set to 123 for reproducibility.
               past_ret and past_vol not included due to data unavailability."
)
