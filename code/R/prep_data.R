suppressPackageStartupMessages({
  library(duckdb)
})

dir.create("data/generated", recursive = TRUE, showWarnings = FALSE)

con <- dbConnect(duckdb())
on.exit(dbDisconnect(con, shutdown = TRUE))

dbExecute(con, "
  CREATE TEMP TABLE filings AS
  SELECT DISTINCT ON (cik_int, filing_year)
    TRY_CAST(cik AS BIGINT) AS cik_int,
    CAST(filingDate AS DATE) AS filing_date,
    TRY_CAST(filing_word_count AS BIGINT) AS word_count,
    YEAR(CAST(filingDate AS DATE)) AS filing_year,
    TRY_CAST(sic AS BIGINT) AS sic,
    sicDescription
  FROM read_parquet('data/pulled/edgar_10k_metadata.parquet')
  WHERE download_success = true
    AND TRY_CAST(filing_word_count AS BIGINT) >= 3000
    AND YEAR(CAST(filingDate AS DATE)) BETWEEN 1995 AND 2023
  ORDER BY cik_int, filing_year, CAST(filingDate AS DATE) DESC
")

n_firm_year <- dbGetQuery(con, "SELECT COUNT(*) FROM filings")[[1]]
dbExecute(con, "
  COPY (
    SELECT
      cik_int,
      filing_date,
      filing_year,
      word_count,
      LN(word_count) AS log_word_count,
      sic,
      sicDescription
    FROM filings
  ) TO 'data/generated/prepared_data.parquet' (FORMAT 'parquet')
")

n_annual <- dbGetQuery(con, "SELECT COUNT(DISTINCT filing_year) FROM filings")[[1]]
dbExecute(con, "
  COPY (
    SELECT
      filing_year,
      COUNT(*) AS n_filings,
      COUNT(DISTINCT cik_int) AS n_firms,
      CAST(ROUND(MEDIAN(word_count)) AS BIGINT) AS median_words,
      CAST(ROUND(AVG(word_count)) AS BIGINT) AS mean_words
    FROM filings
    GROUP BY filing_year
    ORDER BY filing_year
  ) TO 'data/generated/annual_summary.parquet' (FORMAT 'parquet')
")

cat(sprintf("  %s firm-year observations -> data/generated/prepared_data.parquet\n",
            format(n_firm_year, big.mark = ",")))
cat(sprintf("  %s annual rows -> data/generated/annual_summary.parquet\n",
            format(n_annual, big.mark = ",")))
