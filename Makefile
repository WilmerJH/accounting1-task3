all: output/paper.pdf output/presentation.pdf

data/pulled/raw_data.rds: code/R/pull_data.R
	mkdir -p data/pulled
	Rscript --vanilla code/R/pull_data.R

data/generated/prepared_data.rds: code/R/prep_data.R data/pulled/raw_data.rds
	mkdir -p data/generated
	Rscript --vanilla code/R/prep_data.R

output/results.rds: code/R/run_analysis.R data/generated/prepared_data.rds
	mkdir -p output
	Rscript --vanilla code/R/run_analysis.R

output/paper.pdf: doc/paper.qmd output/results.rds
	cd doc && quarto render paper.qmd --to pdf --output paper.pdf
	rm -f doc/paper.tex doc/paper.log doc/paper.aux doc/paper.out doc/paper.knit.md
	rm -f doc/paper.fff doc/paper.ttt doc/texput.log

output/presentation.pdf: doc/presentation.qmd output/results.rds
	cd doc && quarto render presentation.qmd --output presentation.pdf
	rm -f doc/presentation.tex doc/presentation.log doc/presentation.aux doc/presentation.out doc/presentation.knit.md
	rm -rf output/presentation_files

clean:
	rm -rf data/pulled data/generated output .quarto doc/.quarto
	rm -f doc/*.tex doc/*.log doc/*.aux doc/*.out doc/*.knit.md
