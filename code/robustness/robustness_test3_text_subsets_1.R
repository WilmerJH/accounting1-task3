# robustness_test3_text_subsets.R
#
# Robustness Test #3（對應 proposal: "using Part I, Part II, or Item 1A Risk
# Factors separately"）
#
# 【本版本】從 L. Zhang 已下載好的本地 txt 檔讀取，不需要重新下載
# 檔名格式：{cik}_{report_year}_{accession}.txt
#
# 你需要準備的外部資料：
#   (A) txt 資料夾：L. Zhang 的 10k_texts_full/ 資料夾（500+ 個 .txt 檔）
#   (B) LM 字典 CSV：從 https://sraf.nd.edu/loughranmcdonald-master-dictionary/ 下載
#   (C) reg_data：Z. Li 整理好的主迴歸資料（有 car + controls）

suppressPackageStartupMessages({
  library(stringr)
  library(dplyr)
  library(readr)
  library(fixest)
  library(modelsummary)
})

# =============================================================================
# Step 0：填入你自己的路徑（這裡是唯一需要修改的地方）
# =============================================================================

TXT_DIR     <- "C:/Users/Ga/Desktop/R/accounting1-task3-Lingke/data/sec_filings/10k_pilot"  # L. Zhang 的 txt 資料夾路徑
LM_DICT_CSV <- "C:/Users/Ga/Desktop/R/Loughran-McDonald_MasterDictionary_1993-2025.csv"
# REG_DATA_CSV <- "data/generated/main_regression_data.csv"  # 跟 Z. Li 要

# =============================================================================
# Step 1：讀 LM 負面字典
# =============================================================================

load_lm_negative_words <- function(path) {
  dict <- read_csv(path, show_col_types = FALSE)
  tolower(dict$Word[dict$Negative != 0])
}

compute_lm_negtone <- function(text, neg_words) {
  if (is.na(text) || nchar(text) == 0) return(NA_real_)
  words <- str_extract_all(tolower(text), "[a-z]+")[[1]]
  if (length(words) == 0) return(NA_real_)
  sum(words %in% neg_words) / length(words)
}

# =============================================================================
# Step 2：建立「檔名 → cik + report_year」的對照表
# =============================================================================
#
# 檔名格式：0000001800_2020_0001104659-21-025751.txt
#            ↑ cik       ↑ year  ↑ accession

build_file_index <- function(txt_dir) {
  files <- list.files(txt_dir, pattern = "\\.txt$", full.names = TRUE)
  if (length(files) == 0) stop("找不到任何 .txt 檔，請確認 TXT_DIR 路徑正確")

  # 從檔名解析出 cik 和 report_year
  fnames <- basename(files)
  parts  <- str_match(fnames, "^(\\d+)_(\\d{4})_(.+)\\.txt$")

  tibble(
    filepath    = files,
    cik         = parts[, 2],
    report_year = as.integer(parts[, 3])
  ) %>%
    filter(!is.na(cik))  # 排除檔名格式不符的檔案
}

# =============================================================================
# Step 3：從本地 txt 檔切 Item 並算 NegTone
# =============================================================================

# ---- 3a. 找到某個 Item 標題在全文中的位置 ------------------------------------
#
# 策略：找所有「Item XY」的出現，排除「後 60 字內有引號」的（那是內文引用），
#       取剩下的最後一個（正文的 section 標題）
#
# 實測三份真實 SEC txt 檔確認正確：
#   - TOC 通常有引號或页码（會被排除）
#   - 前言的引用有引號（會被排除）
#   - 正文的 section 標題後面是實際內容（會被保留）

find_section_header <- function(text, item_label) {
  pattern <- regex(paste0("item\\s*", item_label, "(?=[.:\\s])"), ignore_case = TRUE)
  pos_mat  <- str_locate_all(text, pattern)[[1]]
  if (nrow(pos_mat) == 0) return(NA_integer_)

  starts <- pos_mat[, "start"]

  # 排除「後 60 字內有引號」的位置（引用，不是 section 標題）
  is_reference <- vapply(starts, function(s) {
    snippet <- str_sub(text, s, min(s + 60, nchar(text)))
    str_detect(snippet, '[\\"\\u201c\\u201d]')
  }, logical(1))

  real_starts <- starts[!is_reference]
  if (length(real_starts) == 0) return(NA_integer_)
  real_starts[length(real_starts)]  # 取最後一個
}

# ---- 3b. 切出兩個 Item 標題之間的內容 ---------------------------------------

extract_item <- function(text, start_label, end_label) {
  s <- find_section_header(text, start_label)
  e <- find_section_header(text, end_label)
  if (is.na(s)) return(NA_character_)
  end_pos <- if (is.na(e) || e <= s) nchar(text) else e - 1
  str_trim(str_sub(text, s, end_pos))
}

# ---- 3c. 讀一個 txt 檔，算出三種 NegTone ------------------------------------

compute_one_file <- function(filepath, neg_words) {
  # 讀取本地 txt（這些已經是純文字，但可能仍有 HTML 標籤殘留）
  raw <- tryCatch(
    readLines(filepath, encoding = "UTF-8", warn = FALSE),
    error = function(e) NULL
  )
  if (is.null(raw)) return(tibble(
    part1_negtone = NA_real_, part2_negtone = NA_real_,
    item1a_negtone = NA_real_, parse_ok = FALSE
  ))

  text <- paste(raw, collapse = "\n")

  # 如果仍有 HTML 標籤（有些 txt 其實是 HTML），用 rvest 再清一次
  if (str_detect(text, "<html|<HTML|<!DOCTYPE")) {
    page <- tryCatch(rvest::read_html(text), error = function(e) NULL)
    if (!is.null(page)) text <- rvest::html_text2(page)
  }

  part1   <- extract_item(text, "1",  "5")
  part2   <- extract_item(text, "5",  "10")
  item_1a <- extract_item(text, "1A", "1B")

  tibble(
    part1_negtone  = compute_lm_negtone(part1,   neg_words),
    part2_negtone  = compute_lm_negtone(part2,   neg_words),
    item1a_negtone = compute_lm_negtone(item_1a, neg_words),
    parse_ok       = TRUE
  )
}

# =============================================================================
# Step 4：批次跑所有本地 txt 檔
# =============================================================================

build_negtone_data <- function(file_index, neg_words, limit = NULL) {
  if (!is.null(limit)) file_index <- head(file_index, limit)

  n   <- nrow(file_index)
  out <- vector("list", n)

  for (i in seq_len(n)) {
    out[[i]] <- tryCatch(
      compute_one_file(file_index$filepath[i], neg_words),
      error = function(e) tibble(
        part1_negtone = NA_real_, part2_negtone = NA_real_,
        item1a_negtone = NA_real_, parse_ok = FALSE
      )
    )
    if (i %% 50 == 0 || i == n)
      cat(sprintf("  進度：%d / %d\n", i, n))
  }

  bind_cols(
    select(file_index, cik, filing_year = report_year),
    bind_rows(out)
  )
}

# =============================================================================
# Step 5：跟主迴歸資料合併，分別跑三個迴歸
# =============================================================================

run_robustness_test3 <- function(reg_data, negtone_data) {
  merged <- reg_data %>%
    left_join(
      filter(negtone_data, parse_ok),  # 只用成功解析的
      by = c("cik", "filing_year")
    )

  f <- ~ size + btm + leverage + roa + loss +
    past_ret + past_vol + log_word_count | industry + filing_year

  list(
    "Part I"  = feols(update(f, car ~ part1_negtone  + .), data = merged, cluster = ~cik),
    "Part II" = feols(update(f, car ~ part2_negtone  + .), data = merged, cluster = ~cik),
    "Item 1A" = feols(update(f, car ~ item1a_negtone + .), data = merged, cluster = ~cik)
  )
}

# =============================================================================
# Step 6：產出比較表
# =============================================================================

make_robustness_table <- function(models) {
  modelsummary(
    models,
    coef_map  = c(
      "part1_negtone"  = "LM NegTone",
      "part2_negtone"  = "LM NegTone",
      "item1a_negtone" = "LM NegTone"
    ),
    title     = "Robustness Test: NegTone Constructed from Different Text Subsets",
    statistic = "({std.error})",
    gof_omit  = "IC|Log|Adj",
    stars     = TRUE,
    notes     = "Standard errors clustered at the firm level."
  )
}

# =============================================================================
# 執行
# =============================================================================

# --- 第一次執行：先確認檔案能被正確找到 ---
 file_index <- build_file_index(TXT_DIR)
 cat("找到", nrow(file_index), "個 txt 檔\n")
 print(head(file_index))   # 確認 cik 和 report_year 解析正確

# --- 讀 LM 字典 ---
 neg_words <- load_lm_negative_words(LM_DICT_CSV)
 cat("LM 負面字共", length(neg_words), "個\n")

# --- 先用 5 筆測試 ---
 test <- build_negtone_data(file_index, neg_words, limit = 5)
 print(test)
# # 確認 parse_ok 是 TRUE、三欄 NegTone 都不是 NA，再繼續

# --- 跑全部 txt 檔（500+ 筆，幾分鐘內完成，不需要網路）---
 negtone_data <- build_negtone_data(file_index, neg_words)
 cat("成功解析:", sum(negtone_data$parse_ok), "/", nrow(negtone_data), "\n")

# --- 跑迴歸（等 Z. Li 的 reg_data）---
# reg_data <- read_csv(REG_DATA_CSV, col_types = cols(cik = col_character()))
# models <- run_robustness_test3(reg_data, negtone_data)
# make_robustness_table(models)
 
 
 
 # result check
 negtone_data %>%
   filter(parse_ok) %>%
   summarise(
     across(
       c(part1_negtone, part2_negtone, item1a_negtone),
       list(
         mean   = ~mean(., na.rm = TRUE),
         median = ~median(., na.rm = TRUE),
         sd     = ~sd(., na.rm = TRUE),
         min    = ~min(., na.rm = TRUE),
         max    = ~max(., na.rm = TRUE),
         n_na   = ~sum(is.na(.))
       )
     )
   ) %>%
   tidyr::pivot_longer(everything()) %>%
   print(n = 999)
