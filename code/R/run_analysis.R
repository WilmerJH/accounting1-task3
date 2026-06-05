suppressPackageStartupMessages({
  library(ggplot2)
})

dir.create("output", recursive = TRUE, showWarnings = FALSE)

analysis_data <- readRDS("data/generated/prepared_data.rds")

model <- lm(mpg ~ wt + transmission, data = analysis_data)
model_coefs <- stats::coef(model)

descriptive_table <- aggregate(
  cbind(mpg, hp, wt) ~ transmission,
  data = analysis_data,
  FUN = function(x) round(mean(x), 1)
)
descriptive_table$n_cars <- as.integer(table(analysis_data$transmission)[descriptive_table$transmission])
descriptive_table <- descriptive_table[, c("transmission", "n_cars", "mpg", "hp", "wt")]
names(descriptive_table) <- c(
  "Transmission",
  "Cars",
  "Mean fuel efficiency (mpg)",
  "Mean horsepower",
  "Mean weight (1,000 lbs)"
)

scatter_figure <- ggplot(
  analysis_data,
  aes(x = wt, y = mpg, color = transmission)
) +
  geom_point(size = 2.6) +
  geom_smooth(
    method = "lm",
    se = FALSE,
    linewidth = 0.8,
    fullrange = TRUE
  ) +
  scale_color_manual(values = c("Automatic" = "#1b6ca8", "Manual" = "#d95f02")) +
  labs(
    x = "Vehicle weight (1,000 lbs)",
    y = "Fuel efficiency (miles per gallon)",
    color = "Transmission"
  ) +
  theme_minimal(base_size = 11) +
  theme(
    legend.position = "top",
    panel.grid.minor = element_blank()
  )

highlights <- list(
  sample_size = nrow(analysis_data),
  avg_mpg = round(mean(analysis_data$mpg), 1),
  avg_weight = round(mean(analysis_data$wt), 2),
  avg_horsepower = round(mean(analysis_data$hp), 1),
  weight_slope = round(unname(model_coefs[["wt"]]), 2),
  manual_effect = round(unname(model_coefs[["transmissionManual"]]), 2),
  fastest_model = analysis_data$model[which.max(analysis_data$mpg)],
  heaviest_model = analysis_data$model[which.max(analysis_data$wt)],
  interpretation = paste(
    "The prepared sample suggests a clear negative relationship between vehicle",
    "weight and fuel efficiency, while the manual cars in this small dataset",
    "have somewhat higher fuel efficiency after controlling for weight."
  )
)

results <- list(
  descriptive_table = descriptive_table,
  scatter_figure = scatter_figure,
  table_note = paste(
    "This table summarizes the prepared mtcars sample by transmission type.",
    "Fuel efficiency is measured in miles per gallon and weight is measured",
    "in 1,000 pounds."
  ),
  highlights = highlights
)

saveRDS(results, file = "output/results.rds")
