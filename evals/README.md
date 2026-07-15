# Eval Runner

`evals.runner` validates the seed eval manifest and writes a lightweight JSON
summary report. It does not execute browser flows; it checks whether the eval
case definitions have the fields needed for later automated scoring.

## Usage

```bash
python -m evals.runner --manifest evals/seed_manifest.json --output data/evals/latest.json
```

When `--output` is omitted, the runner writes to:

```text
data/evals/eval_summary_<timestamp>.json
```

The process exits with a non-zero code when the manifest cannot be loaded or
schema validation produces errors. Warnings are included in the report but do
not fail the run.

## Python API

- `load_manifest(path)` loads a UTF-8 JSON manifest.
- `validate_manifest(manifest)` returns `{"errors": [...], "warnings": [...]}`.
- `summarize_manifest(manifest)` returns aggregate metrics for cases, tags,
  required assertions, required case titles, allowed terminal statuses, and
  forbidden tool coverage.

