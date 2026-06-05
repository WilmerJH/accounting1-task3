dir.create("data/generated", recursive = TRUE, showWarnings = FALSE)

raw_data <- readRDS("data/pulled/raw_data.rds")

prepared_data <- transform(
  raw_data,
  transmission = factor(
    ifelse(am == 1, "Manual", "Automatic"),
    levels = c("Automatic", "Manual")
  ),
  cylinders = factor(cyl, levels = c(4, 6, 8)),
  weight_kg = round(wt * 453.592, 0),
  efficiency_band = ifelse(mpg >= median(mpg), "Higher mpg", "Lower mpg")
)

prepared_data <- prepared_data[
  ,
  c(
    "model", "mpg", "hp", "wt", "weight_kg", "cylinders",
    "transmission", "efficiency_band", "disp", "qsec"
  )
]

saveRDS(prepared_data, file = "data/generated/prepared_data.rds")
