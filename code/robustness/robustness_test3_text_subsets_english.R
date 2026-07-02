# robustness_test3_text_subsets.R
#
# Robustness Test #3: NegTone Constructed from Different Text Subsets
# (Part I only / Part II only / Item 1A Risk Factors only)
#
# Data sources (files located in different branches):
#   main   / data/generated/analysis_sample_car_m1_p1.csv                              -> CAR data (C. Han)
#   main   / data/external/10k_word_counts.csv                                         -> 10-K word counts
#   Lingke / data/external/Loughran-McDonald_MasterDictionary_1993-2025.csv            -> LM dictionary
#   Lingke / data/sec_filings/10k_pilot/                                               -> 500 pilot txt files
#   Zilong / data/generated/controls.csv                                               -> Control variables (Z. Li)
#
# Note: txt files are from the 500-filing pilot sample. Results are preliminary;
#       full-sample results require matching full-text files for the main regression sample.

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

# GitHub API endpoint to list txt files in the pilot folder (Lingke branch)
TXT_FOLDER_API <- "https://api.github.com/repos/WilmerJH/accounting1-task3/contents/data/sec_filings/10k_pilot?ref=Lingke"

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

# Words with Negative != 0 are classified as negative by Loughran-McDonald
neg_words <- read_csv(
  paste0(RAW_LINGKE, "/data/external/Loughran-McDonald_MasterDictionary_1993-2025.csv"),
  show_col_types = FALSE
) %>%
  { tolower(.$Word[.$Negative != 0]) }

cat("Number of LM negative words:", length(neg_words), "\n")

# =============================================================================
# Step 3: Core functions for section extraction and NegTone computation
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
# Step 4: Retrieve txt file list from GitHub and compute NegTone per file
# =============================================================================

# Use GitHub API to get file names and download URLs for all txt files
get_pilot_file_list <- function(api_url) {
  resp <- GET(api_url, timeout(30))
  if (http_error(resp)) stop("Cannot access GitHub API. Check path:\n", api_url)
  content(resp, as = "parsed") %>%
    lapply(function(f) tibble(name = f$name, download_url = f$download_url)) %>%
    bind_rows() %>%
    filter(str_detect(name, "\\.txt$"))
}

# Parse cik and report year from filename (format: {cik}_{year}_{accession}.txt)
parse_filename <- function(fname) {
  m <- str_match(fname, "^(\\d+)_(\\d{4})_.+\\.txt$")
  list(cik = m[2], fyear = as.integer(m[3]))
}

# Download one txt file and compute NegTone for Part I, Part II, and Item 1A
process_one_txt <- function(download_url, neg_words) {
  raw <- tryCatch({
    resp <- GET(download_url, timeout(60))
    if (http_error(resp)) return(NULL)
    content(resp, as = "text", encoding = "UTF-8")
  }, error = function(e) NULL)
  if (is.null(raw)) return(NULL)
  # If the file contains HTML tags, convert to plain text first
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

# Process all txt files and return a data frame with three NegTone columns
build_negtone_subsets <- function(file_list, neg_words) {
  n   <- nrow(file_list)
  out <- vector("list", n)
  for (i in seq_len(n)) {
    info   <- parse_filename(file_list$name[i])
    result <- tryCatch(
      process_one_txt(file_list$download_url[i], neg_words),
      error = function(e) NULL
    )
    out[[i]] <- tibble(
      cik            = info$cik,
      fyear          = info$fyear,
      part1_negtone  = if (is.null(result)) NA_real_ else result$part1_negtone,
      part2_negtone  = if (is.null(result)) NA_real_ else result$part2_negtone,
      item1a_negtone = if (is.null(result)) NA_real_ else result$item1a_negtone
    )
    if (i %% 50 == 0 || i == n)
      cat(sprintf("  Progress: %d / %d\n", i, n))
  }
  bind_rows(out)
}

# =============================================================================
# Step 5: Execute
# =============================================================================

cat("Retrieving txt file list from GitHub...\n")
file_list <- get_pilot_file_list(TXT_FOLDER_API)
cat("Found", nrow(file_list), "txt files\n\n")

cat("Computing NegTone for three text subsets (approx. 15-20 minutes)...\n")
negtone_subsets <- build_negtone_subsets(file_list, neg_words)

cat("\nDescriptive statistics for NegTone subsets:\n")
negtone_subsets %>%
  summarise(across(ends_with("_negtone"),
                   list(mean = ~mean(., na.rm = TRUE),
                        n_na = ~sum(is.na(.))))) %>%
  print()

# =============================================================================
# Step 6: Merge and run regressions
# =============================================================================

reg_data <- car_data %>%
  left_join(negtone_subsets, by = c("cik", "fyear")) %>%
  left_join(controls,        by = c("cik", "fyear")) %>%
  left_join(word_counts,     by = c("cik", "fyear")) %>%
  filter(!is.na(size), !is.na(car))

cat("\nFinal sample size:", nrow(reg_data), "\n")

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
# Step 7: Output comparison table
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
               Based on pilot sample (n=500). Full-sample results to be updated.
               past_ret and past_vol not included due to data unavailability."
)
