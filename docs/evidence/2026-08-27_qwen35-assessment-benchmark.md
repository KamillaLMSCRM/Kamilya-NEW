# Qwen 3.5 4B assessment benchmark

**Run:** 2026-08-27T04:58:55.107047+00:00
**Evidence:** RUNTIME-DERIVED local/provider probe captured by the originating
task. This preserved summary is historical benchmark evidence, not proof of
current provider health, production routing, SLA, or model availability.

## Quality and latency

| Provider | Task | Temp | Status | Valid | Score | Seconds | Tokens |
|---|---|---:|---|---|---:|---:|---:|
| assessment_qwen35_4b | course | 0.2 | ok | True | 10 | 52.048 | 736 |
| assessment_qwen35_4b | writer | 0.2 | ok | False | 8 | 24.065 | 350 |
| assessment_qwen35_4b | quiz | 0.2 | ok | True | 10 | 65.975 | 947 |
| assessment_qwen35_4b | course | 0.3 | ok | True | 10 | 54.061 | 781 |
| assessment_qwen35_4b | writer | 0.3 | ok | True | 10 | 20.544 | 298 |
| assessment_qwen35_4b | quiz | 0.3 | ok | True | 10 | 65.820 | 918 |
| assessment_qwen35_4b | course | 0.4 | ok | True | 10 | 47.485 | 646 |
| assessment_qwen35_4b | writer | 0.4 | ok | False | 6 | 18.906 | 265 |
| assessment_qwen35_4b | quiz | 0.4 | ok | True | 10 | 65.098 | 918 |
| production_qwen38_27b | course | 0.2 | ok | True | 10 | 53.659 | 589 |
| production_qwen38_27b | writer | 0.2 | ok | False | 8 | 8.639 | 87 |
| production_qwen38_27b | quiz | 0.2 | ok | True | 10 | 81.323 | 954 |
| deepseek | course | 0.2 | ok | True | 10 | 4.041 | 575 |
| deepseek | writer | 0.2 | ok | False | 8 | 1.355 | 99 |
| deepseek | quiz | 0.2 | error | False | 0 | 0.496 | not reported |

## Parallel assessment load

| Concurrency | Wall seconds | Mean request seconds | All valid | Main Qwen probe seconds | Main exact |
|---:|---:|---|---|---:|---|
| 1 | 70.466 | 70.453 | True | not measured | not measured |
| 2 | 64.970 | 64.118 | True | not measured | not measured |
| 4 | 67.230 | 66.581 | True | 19.594 | True |

## Interpretation boundary

- The sample is small and task-specific.
- `Score` is the originating evaluator's result and is not a general model
  ranking.
- A successful historical probe does not establish current availability.
- Writer validity failures and the DeepSeek quiz error must remain visible; the
  table does not justify silently promoting a provider.
- A new routing decision requires a fresh benchmark against the current exact
  prompts, schemas, providers, model revisions, concurrency and production-like
  failure behavior.
