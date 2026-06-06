suppressPackageStartupMessages({
  library(duckdb)
  library(httr)
  library(rvest)
})

BASE_URL <- "https://trr266.wiwi.hu-berlin.de/edgar_10k_apr26/"
EDGAR_OUTPUT <- "data/pulled/edgar_10k_metadata.parquet"

list_parquet_files <- function(base_url) {
  response <- GET(base_url, timeout(30))
  stop_for_status(response)
  page <- read_html(content(response, as = "text"))
  links <- html_attr(html_elements(page, "a"), "href")
  links <- links[!is.na(links) & grepl("\\.parquet$", links, ignore.case = TRUE)]
  sort(paste0(base_url, links))
}

duckdb_list_literal <- function(urls) {
  escaped <- gsub("'", "''", urls)
  paste0("['", paste(escaped, collapse = "','"), "']")
}

dir.create("data/pulled", recursive = TRUE, showWarnings = FALSE)

con <- dbConnect(duckdb())
on.exit(dbDisconnect(con, shutdown = TRUE))

parquet_urls <- list_parquet_files(BASE_URL)
file_list <- duckdb_list_literal(parquet_urls)

dbExecute(con, "INSTALL httpfs; LOAD httpfs;")
dbExecute(con, "SET enable_http_metadata_cache = true;")

dbExecute(con, sprintf("
  CREATE OR REPLACE VIEW edgar_10k AS
  SELECT
    cik, name, tickers, exchanges, entityType,
    TRY_CAST(sic AS BIGINT) AS sic, sicDescription,
    stateOfIncorporation, form, filingDate, reportDate,
    accessionNumber, primaryDocUrl, size,
    TRY_CAST(filing_word_count AS BIGINT) AS filing_word_count,
    download_success, download_error
  FROM parquet_scan(%s, union_by_name = true)
", file_list))

dbExecute(con, sprintf(
  "COPY (SELECT * FROM edgar_10k) TO '%s' (FORMAT 'parquet')",
  EDGAR_OUTPUT
))
n <- dbGetQuery(con, "SELECT COUNT(*) FROM edgar_10k")[[1]]
cat(sprintf("  %s rows -> %s\n", format(n, big.mark = ","), EDGAR_OUTPUT))
