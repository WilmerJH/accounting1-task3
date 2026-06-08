# rct-project-template

This repository is the **R version of a barebones project template**. It is meant to be small enough to understand quickly, but structured enough to grow into a real project.

The main idea is simple:

- data are pulled into `data/pulled/`
- data are prepared into `data/generated/`
- analysis writes a serialized results bundle to `output/`
- the presentation slide deck in `doc/` reads those saved results

The example replicates the 10-K word count trend from @DLS2017 using EDGAR filing metadata, and extends their sample to 2023.

## What You Are Looking At

This repository gives you a minimal project skeleton with four visible stages:

1. `code/R/pull_data.R`
2. `code/R/prep_data.R`
3. `code/R/run_analysis.R`
4. `doc/presentation.qmd`

The workflow is organized like a real empirical project. If you later look at `trr266/treat`, you will see the same broad movement in a richer and more elaborate form.

## Project Structure

```text
.devcontainer/
README.md
Makefile
rct-project-template.Rproj
code/R/pull_data.R
code/R/prep_data.R
code/R/run_analysis.R
data/
  external/
  pulled/
  generated/
  data_readme.md
doc/
  presentation.qmd
  references.bib
info/
  edgar_10k_intro.qmd
output/
```

## How The Workflow Moves

The workflow is intentionally explicit:

1. `pull_data.R` fetches EDGAR 10-K filing metadata from the TRR266 server via DuckDB over HTTPS and writes `data/pulled/edgar_10k_metadata.parquet`
2. `prep_data.R` deduplicates, filters, and feature-engineers the raw metadata into `data/generated/prepared_data.parquet` and `data/generated/annual_summary.parquet`
3. `run_analysis.R` reads the prepared data and writes a serialized `.rds` results bundle to `output/`
4. `doc/presentation.qmd` reads that `.rds` bundle and renders the beamer slide deck

The presentation does **not** rerun the full analysis pipeline internally. It uses prepared results from `output/`.

## The `data/` Folder

The `data/` folder keeps the same conceptual separation used in `treat`:

- `data/external/`: files that come from outside the repo and are kept as source material
- `data/pulled/`: raw data written by a pull step
- `data/generated/`: prepared datasets created from raw or external inputs

## The `info/` Folder

`info/edgar_10k_intro.qmd` is a standalone tutorial that shows how to access and query the EDGAR 10-K dataset directly. It is not part of the analysis pipeline but provides a helpful reference for understanding the data source.

## References

The paper cites Dyer, Lang & Stice-Lawrence (2017) and uses `doc/references.bib` for the bibliography.

## Recommended Setup Paths

There are three ways to work with this repo:

1. **GitHub Codespaces**
   This is the recommended path.
2. **Local Docker + browser-based RStudio Server**
   This is the recommended local path.
3. **Fully local install**
   This is possible, but not recommended.

### 1. GitHub Codespaces

1. Use this template on GitHub to create your own repository.
2. Open your repository in Codespaces.
3. Wait for the container to finish building.
4. Open the forwarded port `8787` for RStudio Server.
5. Log in with:
   - username: `rstudio`
   - password: `rstudio`
6. If RStudio Server opens in the home directory and you do not see the project files yet, that is expected. Use `File -> Open Project`, paste `/workspaces/rct-project-template/rct-project-template.Rproj` into the `File name` field, and open it. If your repository folder has a different name, replace the middle `rct-project-template` folder segment with your actual repository folder name.
7. In the RStudio Terminal, run:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
gh auth login
```

Then run:

```bash
make
```

### 2. Local Docker + RStudio Server

Build the image from the repository root:

```bash
docker build -f .devcontainer/Dockerfile -t rct-project-template .
```

Run the container:

```bash
docker run --rm -it \
  -e PASSWORD=rstudio \
  -e USERID=$(id -u) \
  -e GROUPID=$(id -g) \
  -p 8787:8787 \
  -v "$PWD":/workspaces/$(basename "$PWD") \
  -w /workspaces/$(basename "$PWD") \
  rct-project-template
```

Then open `http://localhost:8787` and log in with:

- username: `rstudio`
- password: `rstudio`

Use `File -> Open Project` and paste `/workspaces/rct-project-template/rct-project-template.Rproj` into the `File name` field. Then run:

```bash
git config --global --add safe.directory "$(pwd)"
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
gh auth login
make
```

### 3. Fully Local Install

You can also run the project outside containers, but this is **not recommended** unless you are comfortable managing the stack yourself:

- R
- Quarto
- TinyTeX or another LaTeX installation
- the required R packages: `duckdb`, `ggplot2`, `gt`, `httr`, `rvest`, `htmltools`, `knitr`
- Git and optionally GitHub CLI

If you choose this route, the project command is still:

```bash
make
```

## Main Project Command

Run the whole project from the repository root with:

```bash
make
```

The Makefile runs the full pipeline in order:

1. `code/R/pull_data.R`
2. `code/R/prep_data.R`
3. `code/R/run_analysis.R`
4. `doc/paper.qmd`
5. `doc/presentation.qmd`

## Container Notes

Both Codespaces and the local Docker path provide:

- RStudio Server on port `8787`
- `git`
- `gh`
- Quarto
- TinyTeX
- the R packages needed for this template

This keeps the working environment consistent across students.

## AI Prompts for Common Tasks

Two ready-made prompts are included to help you work with the project configuration using an LLM assistant.

- **`makefile_prompt.md`** — use this if you want to understand how the `Makefile` works or need help adapting it to your own pipeline.
- **`docker_devcontainer_prompt.md`** — use this if you run into errors with the `.devcontainer/` setup or want to understand how the `Dockerfile` and `devcontainer.json` interact.

In each file, replace the text inside the `{{ }}` blocks with your own input, then paste the whole prompt into an LLM of your choice.
