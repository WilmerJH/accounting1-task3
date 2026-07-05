SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

PYTHON := python3
RSCRIPT := Rscript
QUARTO := quarto

# ============================================================
# Big file URLs
# ============================================================

CIK_PERMNO_URL := https://box.hu-berlin.de/seafhttp/f/4ba3a85005c34c6eaeaa/?op=view
RET_URL := https://box.hu-berlin.de/seafhttp/f/12914e5a8d764a6f960b/?op=view

# ============================================================
# Input and output paths
# ============================================================

# External large files
CIK_PERMNO_FILE := data/external/cik_to_permno.csv.gz
RET_FILE := data/external/ret_all.csv.gz
INDEX_FILE := data/external/index.csv

# Tone outputs
TONE_SAMPLE := data/generated/tone/full_10k_sample_dedup_stratified_1500_per_year.csv
TONE_RESULT := data/generated/tone/stratified_1500_lm_negtone_results.csv
TONE_SUMMARY := data/generated/tone/stratified_1500_lm_negtone_summary.csv

# CAR outputs
CAR_RESULT := data/generated/CAR/10k_sample_with_car.csv
CAR_ANALYSIS := data/generated/CAR/analysis_sample_car_m1_p1.csv
CAR_TEMP := data/generated/CAR/ret_filtered.parquet

# Regression outputs
CONTROLS := data/generated/regression/controls.csv
REG_SAMPLE := data/generated/regression/main_regression_sample.csv
REG_TABLE := output/tables/main_regression.html

# Quarto file
QMD := doc/slide.qmd
PDF := doc/slide.pdf

# ============================================================
# Main commands
# ============================================================

.PHONY: all tone download-big-files car regression pdf clean clean-temp

all: tone download-big-files car regression pdf

# ============================================================
# 1. Tone pipeline
# ------------------------------------------------------------
# Order:
# 01 -> 01a -> 05 -> 07 creates the stratified sample list.
# 06 then uses that stratified sample as input and generates
# stratified_1500_lm_negtone_results.csv for regression.
# ============================================================

tone: $(TONE_RESULT) $(TONE_SUMMARY)

$(TONE_SAMPLE): \
	code/tone/01_descriptive_10k_sample.py \
	code/tone/01a_classify_duplicate_groups.py \
	code/tone/05_build_dedup_full_sample.py \
	code/tone/07_make_stratified_negtone_sample.py
	mkdir -p data/generated/tone
	$(PYTHON) code/tone/01_descriptive_10k_sample.py
	$(PYTHON) code/tone/01a_classify_duplicate_groups.py
	$(PYTHON) code/tone/05_build_dedup_full_sample.py
	$(PYTHON) code/tone/07_make_stratified_negtone_sample.py

$(TONE_RESULT) $(TONE_SUMMARY): \
	$(TONE_SAMPLE) \
	code/tone/06_run_full_lm_negtone.py \
	code/tone/lm_negtone_utils.py \
	code/tone/sec_download_utils.py
	mkdir -p data/generated/tone
	$(PYTHON) code/tone/06_run_full_lm_negtone.py \
		--input $(TONE_SAMPLE) \
		--output $(TONE_RESULT) \
		--summary $(TONE_SUMMARY) \
		--cache-only

# ============================================================
# 2. Download big files and run CAR
# ============================================================

download-big-files: $(CIK_PERMNO_FILE) $(RET_FILE)

$(CIK_PERMNO_FILE):
	mkdir -p data/external
	wget -O $(CIK_PERMNO_FILE) "$(CIK_PERMNO_URL)"

$(RET_FILE):
	mkdir -p data/external
	wget -O $(RET_FILE) "$(RET_URL)"

car: $(CAR_RESULT) $(CAR_ANALYSIS)

$(CAR_RESULT) $(CAR_ANALYSIS): \
	$(TONE_RESULT) \
	$(CIK_PERMNO_FILE) \
	$(RET_FILE) \
	$(INDEX_FILE) \
	code/CAR/car.py
	mkdir -p data/generated/CAR
	$(PYTHON) code/CAR/car.py

# ============================================================
# 3. Regression pipeline
# ------------------------------------------------------------
# construct_controls.R creates:
#   data/generated/regression/controls.csv
#
# main_regression.R creates:
#   data/generated/regression/main_regression_sample.csv
#   output/tables/main_regression.html
# ============================================================

regression: $(REG_SAMPLE) $(REG_TABLE)

$(CONTROLS): code/regression/construct_controls.R
	mkdir -p data/generated/regression
	$(RSCRIPT) code/regression/construct_controls.R

$(REG_SAMPLE) $(REG_TABLE): \
	$(TONE_RESULT) \
	$(CAR_RESULT) \
	$(CONTROLS) \
	code/regression/main_regression.R
	mkdir -p data/generated/regression
	mkdir -p output/tables
	$(RSCRIPT) code/regression/main_regression.R

# ============================================================
# 4. Render Quarto PDF
# ============================================================

pdf: $(PDF)

$(PDF): $(QMD) $(REG_SAMPLE) $(REG_TABLE)
	cd doc && $(QUARTO) render slide.qmd --to beamer

# ============================================================
# Cleanup
# ============================================================

clean-temp:
	rm -f $(CAR_TEMP)

clean:
	rm -f $(TONE_RESULT)
	rm -f $(TONE_SUMMARY)
	rm -f $(CAR_RESULT)
	rm -f $(CAR_ANALYSIS)
	rm -f $(CAR_TEMP)
	rm -f $(CONTROLS)
	rm -f $(REG_SAMPLE)
	rm -f $(REG_TABLE)
	rm -f $(PDF)