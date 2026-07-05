# robustness_test3_text_subsets_eng.R
#
# Robustness Test #3: NegTone Constructed from Different Text Subsets
# Part I only / Part II only / Item 1A Risk Factors only
#
# Local data sources:
#   data/generated/CAR/analysis_sample_car_m1_p1.csv
#   data/generated/tone/full_10k_sample_dedup_stratified_1500_per_year.csv
#   data/external/10k_word_counts.csv
#   data/external/Loughran-McDonald_MasterDictionary_1993-2025.csv
#   data/generated/regression/controls.csv
#   data/pulled/sec_filings/
#
# Outputs:
#   data/generated/tone/robustness_test3_text_subsets_negtone.csv
#   output/robustness_test3_text_subsets.html

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(stringr)
  library(fixest)
  library(modelsummary)
  library(rvest)
})

# =============================================================================
# Project paths
# =============================================================================

# Run this script from the repository root
PROJECT_ROOT <- "."

LOCAL_FILING_DIR <- file.path(PROJECT_ROOT, "data/pulled/sec_filings")

dir.create(file.path(PROJECT_ROOT, "output"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(PROJECT_ROOT, "data/generated/tone"), recursive = TRUE, showWarnings = FALSE)
dir.create(file.path(PROJECT_ROOT, "data/generated/regression"), recursive = TRUE, showWarnings = FALSE)

# Random seed for reproducibility of stratified sample
RANDOM_SEED <- 123
N_PER_YEAR  <- 87

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

pad_cik10 <- function(x) {
  str_pad(clean_cik(x), width = 10, side = "left", pad = "0")
}

extract_accession <- function(url) {
  url <- as.character(url)

  # Case 1: URL contains dashed accession number
  dashed <- str_extract(url, "\\d{10}-\\d{2}-\\d{6}")
  if (!is.na(dashed)) return(dashed)

  # Case 2: SEC URL contains accession number without dashes
  nodash <- str_extract(url, "\\d{18}")
  if (!is.na(nodash)) {
    return(paste0(
      substr(nodash, 1, 10), "-",
      substr(nodash, 11, 12), "-",
      substr(nodash, 13, 18)
    ))
  }

  NA_character_
}

find_local_filing <- function(cik, fyear, url) {
  cik10 <- pad_cik10(cik)
  accession <- extract_accession(url)

  if (is.na(accession)) return(NA_character_)

  expected_path <- file.path(
    LOCAL_FILING_DIR,
    paste0(cik10, "_", fyear, "_", accession, ".txt")
  )

  if (file.exists(expected_path)) {
    return(expected_path)
  }

  # Fallback: search by accession number in local filings
  candidates <- list.files(
    LOCAL_FILING_DIR,
    pattern = accession,
    recursive = TRUE,
    full.names = TRUE
  )

  if (length(candidates) > 0) {
    return(candidates[1])
  }

  NA_character_
}

# Find the position of the last true section header for a given Item label.
find_section_header <- function(text, item_label) {
  pattern <- regex(paste0("item\\s*", item_label, "(?=[.:\\s])"), ignore_case = TRUE)
  pos_mat <- str_locate_all(text, pattern)[[1]]

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

# Read one local 10-K filing and compute NegTone for three sections
process_one_filing <- function(local_file, neg_words) {
  raw <- tryCatch({
    read_file(local_file, locale = locale(encoding = "UTF-8"))
  }, error = function(e) NULL)

  if (is.null(raw)) return(NULL)

  # Convert HTML to plain text if needed
  if (str_detect(raw, "<html|<HTML|<!DOCTYPE")) {
    page <- tryCatch(read_html(raw), error = function(e) NULL)
    if (!is.null(page)) {
      raw <- html_text2(page)
    }
  }

  list(
    part1_negtone  = compute_lm_negtone(extract_item(raw, "1",  "5"),  neg_words),
    part2_negtone  = compute_lm_negtone(extract_item(raw, "5",  "10"), neg_words),
    item1a_negtone = compute_lm_negtone(extract_item(raw, "1A", "1B"), neg_words)
  )
}

build_negtone_subsets <- function(meta_sample, neg_words) {
  n <- nrow(meta_sample)
  out <- vector("list", n)

  for (i in seq_len(n)) {
    result <- tryCatch(
      process_one_filing(meta_sample$local_file[i], neg_words),
      error = function(e) NULL
    )

    out[[i]] <- tibble(
      cik            = meta_sample$cik[i],
      fyear          = meta_sample$fyear[i],
      local_file     = meta_sample$local_file[i],
      part1_negtone  = if (is.null(result)) NA_real_ else result$part1_negtone,
      part2_negtone  = if (is.null(result)) NA_real_ else result$part2_negtone,
      item1a_negtone = if (is.null(result)) NA_real_ else result$item1a_negtone,
      parse_ok       = !is.null(result)
    )

    if (i %% 100 == 0 || i == n) {
      cat(sprintf(
        "  Progress: %d / %d  (successful: %d)\n",
        i, n, sum(sapply(out[1:i], function(x) x$parse_ok))
      ))
    }
  }

  bind_rows(out)
}

# =============================================================================
# Step 1: Load CAR, controls, and word counts
# =============================================================================

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
# Step 2: Load LM negative word dictionary
# =============================================================================

neg_words <- read_csv(
  file.path(PROJECT_ROOT, "data/external/Loughran-McDonald_MasterDictionary_1993-2025.csv"),
  show_col_types = FALSE
) %>%
  { tolower(.$Word[.$Negative != 0]) }

cat("Number of LM negative words:", length(neg_words), "\n")

# =============================================================================
# Step 3: Load metadata and match to local filings
# =============================================================================

meta_full <- read_csv(
  file.path(PROJECT_ROOT, "data/generated/tone/full_10k_sample_dedup_stratified_1500_per_year.csv"),
  col_types = cols(cik = col_character()),
  show_col_types = FALSE
) %>%
  mutate(
    cik = clean_cik(cik),
    fyear = as.integer(report_year)
  )

meta_with_local_paths <- meta_full %>%
  filter(!is.na(url), download_success == TRUE) %>%
  mutate(
    local_file = mapply(find_local_filing, cik, fyear, url)
  )

cat("\n--- Local filing diagnostics ---\n")
cat("Metadata rows:", nrow(meta_with_local_paths), "\n")
cat("Rows with local filing text:", sum(!is.na(meta_with_local_paths$local_file)), "\n")
cat("Rows without local filing text:", sum(is.na(meta_with_local_paths$local_file)), "\n")

if (sum(!is.na(meta_with_local_paths$local_file)) == 0) {
  stop("No local filing text files matched. Check LOCAL_FILING_DIR and local filename pattern.")
}

# Stratified sample: up to N_PER_YEAR filings per year
set.seed(RANDOM_SEED)

meta_sample <- meta_with_local_paths %>%
  filter(!is.na(local_file)) %>%
  group_by(report_year) %>%
  group_modify(~ slice_sample(.x, n = min(N_PER_YEAR, nrow(.x)))) %>%
  ungroup() %>%
  select(cik, fyear, local_file)

cat("\nStratified sample size:", nrow(meta_sample), "filings\n")
cat("Year distribution:\n")
print(table(meta_sample$fyear))

# =============================================================================
# Step 4: Read local filings and compute NegTone subsets
# =============================================================================

cat("\nReading", nrow(meta_sample), "local filings from", LOCAL_FILING_DIR, "...\n\n")

negtone_subsets <- build_negtone_subsets(meta_sample, neg_words) %>%
  mutate(
    cik = clean_cik(cik),
    fyear = as.integer(fyear)
  )

write_csv(
  negtone_subsets,
  file.path(PROJECT_ROOT, "data/generated/tone/robustness_test3_text_subsets_negtone.csv")
)

cat("\nLocal filing parse success rate:",
    sum(negtone_subsets$parse_ok), "/", nrow(negtone_subsets), "\n")

cat("\nDescriptive statistics for NegTone subsets:\n")

desc_stats <- negtone_subsets %>%
  filter(parse_ok) %>%
  summarise(across(
    ends_with("_negtone"),
    list(
      mean = ~mean(., na.rm = TRUE),
      n_na = ~sum(is.na(.))
    )
  ))

print(desc_stats)

write_csv(
  desc_stats,
  file.path(PROJECT_ROOT, "data/generated/tone/robustness_test3_text_subsets_desc.csv")
)

cat("\nFinished descriptive statistics. Starting merge...\n")

# =============================================================================
# Step 5: Merge and run regressions
# =============================================================================

merged_data <- car_data %>%
  left_join(negtone_subsets %>% filter(parse_ok),
            by = c("cik", "fyear")) %>%
  left_join(controls, by = c("cik", "fyear")) %>%
  left_join(word_counts, by = c("cik", "fyear"))

cat("Finished merge. Starting regression data filtering...\n")

cat("\n--- Merge diagnostics ---\n")
cat("Merged sample size:", nrow(merged_data), "\n")
cat("Missing part1_negtone: ", sum(is.na(merged_data$part1_negtone)), "\n")
cat("Missing part2_negtone: ", sum(is.na(merged_data$part2_negtone)), "\n")
cat("Missing item1a_negtone:", sum(is.na(merged_data$item1a_negtone)), "\n")
cat("Missing size:          ", sum(is.na(merged_data$size)), "\n")
cat("Missing car:           ", sum(is.na(merged_data$car)), "\n")
cat("Missing log_word_count:", sum(is.na(merged_data$log_word_count)), "\n")

reg_data <- merged_data %>%
  filter(!is.na(size), !is.na(car))

cat("\nFinal regression sample size:", nrow(reg_data), "\n")

if (nrow(reg_data) == 0) {
  stop("Regression sample is empty. Check CIK and fyear matching across input files.")
}

# =============================================================================
# Step 6: Run regressions
# =============================================================================

cat("\nStarting regressions...\n")

models <- list(
  "Part I" = feols(
    car ~ part1_negtone + size + btm + leverage + roa +
      loss + log_word_count | sic2 + fyear,
    data = reg_data,
    cluster = ~cik
  ),

  "Part II" = feols(
    car ~ part2_negtone + size + btm + leverage + roa +
      loss + log_word_count | sic2 + fyear,
    data = reg_data,
    cluster = ~cik
  ),

  "Item 1A" = feols(
    car ~ item1a_negtone + size + btm + leverage + roa +
      loss + log_word_count | sic2 + fyear,
    data = reg_data,
    cluster = ~cik
  )
)

# =============================================================================
# Step 7: Output comparison table
# =============================================================================

cat("\nFinished regressions. Writing HTML table...\n")

modelsummary(
  models,
  coef_map = c(
    "part1_negtone"  = "LM NegTone",
    "part2_negtone"  = "LM NegTone",
    "item1a_negtone" = "LM NegTone"
  ),
  title = "Robustness Test: NegTone from Different Text Subsets",
  statistic = "({std.error})",
  gof_map = c("nobs", "r.squared"),
  stars = TRUE,
  notes = "Standard errors clustered at the firm level.
           All models include industry (2-digit SIC) and year fixed effects.
           NegTone is computed from local 10-K filing text files.
           Based on a stratified random sample of up to 87 filings per year.
           Seed set to 123 for reproducibility.
           past_ret and past_vol not included due to data unavailability.",
  output = file.path(PROJECT_ROOT, "output/robustness_test3_text_subsets.html")
)

cat("\nDone. Output written to output/robustness_test3_text_subsets.html\n")