This repository keeps the `treat`-style data separation in a minimal form.

- `data/external/` is for source files that come from outside the repository.
- `data/pulled/` is for raw data written by a pull step.
- `data/generated/` is for prepared datasets created from pulled or external inputs.

In this tiny template, the pull step uses the built-in `mtcars` dataset, so `data/external/` is empty by default. The folder is still present so that students can later adapt the structure to their own projects.
