# Browser-Use Alignment Smoke Benchmark

Date: 2026-06-05
Scope: WV-001, WV-005, WV-007
Sample size: 3 cases

## Purpose

Evaluate whether recent page-context, target-selection, and extraction changes
improved the internal agent on a small WebVoyager subset.

## Result

| Run | Passed | Rate |
|---|---:|---:|
| Initial aligned run | 1/3 | 33.3% |
| Follow-up run | 2/3 | 66.7% |

The sample is too small to establish a stable success rate. A single case
changes the rate by 33 percentage points.

## Observations

- WV-001 remained successful.
- WV-007 improved after stronger multi-field extraction guidance.
- WV-005 progressed further but still failed around page stabilization and
  extraction timing.

## Decisions

- Keep this document as qualitative benchmark evidence only.
- Do not use the 66.7% result as a release gate.
- Generated per-run markdown and logs are runtime output and are not retained
  in Git.
- Future comparisons should use the reproducible runner under
  `tests/benchmarks/webvoyager_subset/`.
- Broaden the sample before changing default browser-resolution strategy.

## Reproduction

Use the benchmark runner help for current options:

```powershell
python tests/benchmarks/webvoyager_subset/runner.py --help
```

Store generated output under ignored `data/` paths.
