dir.create("data/pulled", recursive = TRUE, showWarnings = FALSE)

mtcars_raw <- transform(
  mtcars,
  model = rownames(mtcars)
)
rownames(mtcars_raw) <- NULL

saveRDS(mtcars_raw, file = "data/pulled/raw_data.rds")
