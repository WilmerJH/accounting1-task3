# rct-project-template

This repository is the **R version of a barebones project template**. It is meant to be small enough to understand quickly, but structured enough to grow into a real project.

The main idea is simple:

- data are pulled into `data/pulled/`
- data are prepared into `data/generated/`
- analysis writes a serialized results bundle to `output/`
- the paper in `doc/` reads those saved results

So even though the example uses the tiny `mtcars` dataset, the workflow is already organized like a real empirical project.

## What You Are Looking At

This repository gives you a minimal project skeleton with four visible stages:

1. `code/R/pull_data.R`
2. `code/R/prep_data.R`
3. `code/R/run_analysis.R`
4. `doc/paper.qmd`

The point is not the `mtcars` analysis itself. The point is to give you a clean starting structure that you can keep extending for your own work.

If you later look at `trr266/treat`, you will see the same broad movement in a richer and more elaborate form.

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
  paper.qmd
  references.bib
output/
```

## How The Workflow Moves

The workflow is intentionally explicit:

1. `pull_data.R` creates a raw object in `data/pulled/`
2. `prep_data.R` reads that raw object and creates a prepared analysis dataset in `data/generated/`
3. `run_analysis.R` reads the prepared dataset and writes a serialized `.rds` results bundle to `output/`
4. `doc/paper.qmd` reads that `.rds` bundle and renders the paper

The paper does **not** rerun the full analysis pipeline internally. It consumes prepared results from `output/`.

## The `data/` Folder

The `data/` folder keeps the same conceptual separation used in `treat`:

- `data/external/`: files that come from outside the repo and are kept as source material
- `data/pulled/`: raw data written by a pull step
- `data/generated/`: prepared datasets created from raw or external inputs

In this template, the pull step uses the built-in `mtcars` dataset, so `data/external/` starts empty. The folder is still there so you can swap in your own real project data later without changing the overall structure.

## References

The paper also includes a minimal bibliography workflow. The bibliography file lives at:

- `doc/references.bib`

and `doc/paper.qmd` cites at least one reference from that file. That way you can already see the basic citation pattern in a working template rather than adding it later from scratch.

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

The repository is mounted at `/workspaces/<your-repo-folder>`. If RStudio Server opens in the home directory and you do not see the project files yet, that is expected. Use `File -> Open Project`, paste `/workspaces/rct-project-template/rct-project-template.Rproj` into the `File name` field, and open it. If your repository folder has a different name, replace the middle `rct-project-template` folder segment with your actual repository folder name. Then run:

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
- the required R packages
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

## Outputs

The main analytical output is:

- `output/rct-project-template-results.rds`

The final paper is written to:

- `output/rct-project-template-paper.pdf`

That paper imports one saved descriptive table and one saved figure from the results bundle. The analytical objects are prepared first, then rendered in the paper.

## The Paper

The paper source lives in:

- `doc/paper.qmd`

It is formatted as a small article-style paper so the repository already feels like a miniature research template rather than a single script with a report attached at the end.
The current template shows one descriptive table, one figure, and one bibliography entry so the reporting workflow stays visible without becoming crowded.

## AI Prompts for Common Tasks

Two ready-made prompts are included to help you work with the project configuration using an LLM assistant.

- **`makefile_prompt.md`** — use this if you want to understand how the `Makefile` works or need help adapting it to your own pipeline.
- **`docker_devcontainer_prompt.md`** — use this if you run into errors with the `.devcontainer/` setup or want to understand how the `Dockerfile` and `devcontainer.json` interact.

In each file, replace the text inside the `{{ }}` blocks with your own input, then paste the whole prompt into an LLM of your choice.


## Container Notes

Both Codespaces and the local Docker path provide:

- RStudio Server on port `8787`
- `git`
- `gh`
- Quarto
- TinyTeX
- the R packages needed for this template

This keeps the working environment consistent across students.
