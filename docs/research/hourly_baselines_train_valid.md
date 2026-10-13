# Fixed hourly baselines: TRAIN / VALID development round

Status: all six attempts computed and retained as **INVALID**. No performance claim can be made from them.

Experiment **4252** was preregistered before measurements. It declares the three fixed definitions, BTCUSDT hourly, seed 0, 168 explicit warm-up rows, accepted fees/gates, a VALID batch integration check followed by complete TRAIN/VALID comparisons, and retention of every attempt. No parameter, seed or score selection occurred.

Source: `2af11410a3c23ea8918b7e0ef5b92ea8a5497a7b`, clean (`dirty=false`) for every comparison. Snapshot: `9d75c8de86a8e981a9af61b17f76d1a7efc225f3d554366a152ba8f03968824f`. Accepted split dates are unchanged. TEST accesses for the three baselines remain **0**.

| Alpha | Split | Input rows | Unavailable after warm-up | Outcome |
|---|---|---:|---:|---|
| baseline_b0 | TRAIN | 43705 | 643 | INVALID |
| baseline_b0 | VALID | 12959 | 24 | INVALID |
| baseline_b1 | TRAIN | 43705 | 4028 | INVALID |
| baseline_b1 | VALID | 12959 | 168 | INVALID |
| baseline_b2 | TRAIN | 43705 | 4176 | INVALID |
| baseline_b2 | VALID | 12959 | 168 | INVALID |

All attempts record DATA_GAPS and UNAVAILABLE_AFTER_WARMUP. TRAIN/VALID history is not a complete usable hourly series under the fixed features and strict availability contract. The simulator does not remove gaps, fill signals, or insert apparent flat returns to produce attractive metrics. Sharpe, Fitness, equity, cost sensitivity and monthly performance therefore remain N/A; these are data-validity failures, not evidence that the strategies lose money.

The three earlier VALID batch-check attempts are also retained under this experiment with clean source `163491f`. They are not silently replaced by these six comparison attempts. Alpha versions, cost assumptions, dates and gates were not changed after inspection. A later documented data-quality/execution policy would be needed before drawing performance conclusions; no such change is made here.

Each artifact was checked against its registered SHA-256 and each HTML report generated from that verified evidence. Raw files stay outside Git. `report.html` shows the latest view and content-hashed archives preserve both TRAIN and VALID reports.

| Alpha / split | Run ID | Artifact SHA-256 |
|---|---|---|
| baseline_b0 / train | `7a121c5e-f0a6-4ef3-a9b6-bbb8643ac65c` | `1c4d5bc31d5ee4ab54c4ab486dfa9c210596b8bbf078ca4a219eadb7e3c2b467` |
| baseline_b0 / valid | `69c77247-0ece-4bf5-9914-6934e6fd6e20` | `fc8671b56f934c35cbe4e3488a041c2a5d89f1ec92438a38ca25160b09da8853` |
| baseline_b1 / train | `47498b7a-b412-4d42-af36-fd2142131f08` | `538761ff8bbdd6be7e1311331b5542c1174224504db641ea996cad8cf8e73a03` |
| baseline_b1 / valid | `2dfbae8f-85ec-4b82-99d6-7bd1c4458f64` | `09d41a9e6546e85fdf12285d92ad58643c815dfce12289f15b5a6b5aa0ca6ade` |
| baseline_b2 / train | `3a2c832f-63d5-4199-8e26-f3bd24ced59a` | `66f2221b1fb319b505d654313587c005e2289cb7388d3c78e92a197d2e088f88` |
| baseline_b2 / valid | `0d0b9b4e-d96f-4b90-83c8-8ff4dcf53d17` | `7748a76dad2af0394aaeb989b3419748a227423d8a9a86e5f698041e77a01a53` |
