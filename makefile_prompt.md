I need help understanding and updating a Makefile for a research project. 
The project follows this data pipeline:

{{

YOUR INPUT: 

Describe the workflow of your analysis similar to our example from the template.
Make sure that all file names are spelled correctly and have relative paths starting at the project root.

Example (to be replaced by your workflow):

1. `pull_data.R` creates a raw data file saved to `data/pulled/`
2. `prep_data.R` reads that raw file and saves a prepared dataset to `data/generated/`
3. `run_analysis.R` reads the prepared dataset and saves a results bundle (`.rds`) to `output/`
4. `doc/paper.qmd` reads that results bundle and renders the final paper.

}}

Here is an example Makefile that implements a similar workflow:

```makefile
RSCRIPT := Rscript --vanilla
QUARTO := quarto

PULLED := data/pulled/mtcars_raw.rds
GENERATED := data/generated/mtcars_prepared.rds
RESULTS := output/rct-project-template-results.rds
OLD_RESULTS := output/rct-github-intro-results.rds
PAPER_BASENAME := rct-project-template-paper.pdf
OLD_PAPER := output/rct-github-intro-paper.pdf
PAPER := output/$(PAPER_BASENAME)
SOURCE := doc/paper.qmd

.PHONY: all clean

all: $(PAPER)

$(PULLED): code/R/pull_data.R
	mkdir -p data/pulled
	$(RSCRIPT) $<

$(GENERATED): code/R/prep_data.R $(PULLED)
	mkdir -p data/generated
	$(RSCRIPT) $<

$(RESULTS): code/R/run_analysis.R $(GENERATED)
	mkdir -p output
	$(RSCRIPT) $<

$(PAPER): $(SOURCE) $(RESULTS)
	rm -rf .quarto doc/.quarto
	cd doc && $(QUARTO) render paper.qmd --to pdf --output $(PAPER_BASENAME)
	rm -f paper.tex paper.log paper.aux paper.out paper.knit.md
	rm -f $(PAPER_BASENAME)
	rm -f texput.log doc/texput.log
	rm -f doc/paper.tex doc/paper.log doc/paper.aux doc/paper.out doc/paper.knit.md doc/paper.fff doc/paper.ttt

clean:
	rm -rf .quarto doc/.quarto
	rm -f $(PULLED) $(GENERATED) $(RESULTS) $(PAPER) $(OLD_RESULTS) $(OLD_PAPER)
	rm -f paper.tex paper.log paper.aux paper.out paper.knit.md
	rm -f texput.log doc/texput.log
	rm -f doc/paper.tex doc/paper.log doc/paper.aux doc/paper.out doc/paper.knit.md doc/paper.fff doc/paper.ttt
```

Please help me understand how this Makefile works and how to make a barebones, super simple version for my specific project. I want to simplify the syntax so that it is easier to read and maintain.
