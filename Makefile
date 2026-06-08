all: output/presentation.pdf

data/pulled/edgar_10k_metadata.parquet: code/R/pull_data.R
	mkdir -p data/pulled
	Rscript --vanilla code/R/pull_data.R

data/generated/prepared_data.parquet: code/R/prep_data.R data/pulled/edgar_10k_metadata.parquet
	mkdir -p data/generated
	Rscript --vanilla code/R/prep_data.R

output/results.rds: code/R/run_analysis.R data/generated/prepared_data.parquet
	mkdir -p output
	Rscript --vanilla code/R/run_analysis.R

output/presentation.pdf: doc/presentation.qmd output/results.rds
	cd doc && quarto render presentation.qmd --output presentation.pdf
	rm -f doc/presentation.tex doc/presentation.log doc/presentation.aux doc/presentation.out doc/presentation.knit.md
	rm -rf output/presentation_files

clean:
	rm -rf data/pulled data/generated output .quarto doc/.quarto
	rm -f doc/*.tex doc/*.log doc/*.aux doc/*.out doc/*.knit.md
