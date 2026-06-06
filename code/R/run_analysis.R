suppressPackageStartupMessages({
  library(duckdb)
  library(ggplot2)
  library(gt)
})

dir.create("output", recursive = TRUE, showWarnings = FALSE)

con <- dbConnect(duckdb())
data   <- dbGetQuery(con, "SELECT * FROM read_parquet('data/generated/prepared_data.parquet')")
annual <- dbGetQuery(con, "SELECT * FROM read_parquet('data/generated/annual_summary.parquet')")
dbDisconnect(con, shutdown = TRUE)

make_length_figure <- function(annual_data) {
  ggplot(annual_data, aes(x = filing_year, y = median_words)) +
    geom_line(linewidth = 0.8, color = "#1b6ca8") +
    geom_point(size = 1.8, color = "#1b6ca8") +
    scale_x_continuous(breaks = c(1995, 2000, 2005, 2010, 2015, 2020)) +
    labs(x = "Filing year", y = "Median word count") +
    theme_minimal(base_size = 11) +
    theme(
      panel.grid.minor = element_blank(),
      axis.text.x = element_text(angle = 45, hjust = 1)
    )
}

prepare_annual_table <- function(annual_data) {
  gt(annual_data) |>
    cols_label(
      filing_year  = "Year",
      n_filings    = "Filings",
      n_firms      = "Firms",
      median_words = "Median words",
      mean_words   = "Mean words"
    ) |>
    fmt_integer(columns = c(n_filings, n_firms, median_words, mean_words)) |>
    cols_align(
      align   = "right",
      columns = c(n_filings, n_firms, median_words, mean_words)
    ) |>
    tab_source_note(md(paste0(
      "*Note*: Sample restricted to 10-K filings with ≥ 3,000 words ",
      "and successful markdown conversion, one per firm per calendar year."
    ))) |>
    tab_options(table.font.size = px(12), data_row.padding = px(2.5))
}

annual_table  <- prepare_annual_table(annual)
length_figure <- make_length_figure(annual)

first_year <- min(annual$filing_year)
last_year  <- max(annual$filing_year)

highlights <- list(
  sample_size        = nrow(data),
  year_range         = paste0(first_year, "–", last_year),
  n_firms            = length(unique(data$cik_int)),
  median_words_first = annual$median_words[annual$filing_year == first_year],
  median_words_last  = annual$median_words[annual$filing_year == last_year]
)

results <- list(
  annual_table  = annual_table,
  annual_data   = annual,
  length_figure = length_figure,
  highlights    = highlights
)

saveRDS(results, file = "output/results.rds")
