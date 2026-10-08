# Building the feature store (step 083)

From the project root in the documented WSL environment:

```bash
uv run python scripts/build_features.py --interval 1h
uv run python scripts/build_features.py --interval 1m --symbol BTCUSDT
```

With no `--symbol`, all coins in `configs/universe.yaml` are built. Repeat `--symbol`
to select multiple coins. `--bars-dir` and `--out-dir` override the canonical bar
and feature roots. The interval is the only change needed between hourly and minute
builds; feature lookbacks are measured in bars. The default build covers each coin's
entire stored history, without applying TRAIN/VALID/TEST splits or reading labels.

## Layout and schema

```text
data/processed/features/
  feature_set=v1/interval=1h/symbol=BTCUSDT/
    manifest.json
    year=2017/features.parquet
    year=2018/features.parquet
    ...
```

Each zstd-compressed Parquet file contains integer UTC-microsecond `open_time`,
one float64 column per registered feature, and one boolean `available__<feature>`
column per feature. The partition path supplies feature-set version, interval,
symbol and UTC year when read with Hive partitioning. One coin's full series is
computed before splitting into years, preserving lookback history across December
and January. Coins are computed independently.

Unavailable values are NaN and their masks are false. Consumers must use the mask;
zero is a valid feature value and must not replace unavailable data. Missing time
intervals are not filled. Off-grid source candles remain in the export with all
features unavailable, and their number appears in the console and manifest. Raw
bars are unchanged. A symbol with no on-grid observations fails explicitly.

Example inspection of an individual partition:

```python
import pandas as pd

frame = pd.read_parquet(
    "data/processed/features/feature_set=v1/interval=1h/"
    "symbol=BTCUSDT/year=2025/features.parquet"
)
usable = frame.loc[frame["available__log_return_24"], ["open_time", "log_return_24"]]
```

## Provenance and rebuilding

Each symbol's manifest records the feature descriptions/units/lookbacks/warm-up,
config fingerprint, code commit, dirty status, seed, build time, exact source-file
hashes and snapshot ID, output-file hashes, row count, off-grid count, and availability
fractions. This is a deterministic derived-data build, not a trading-result report.
Development builds explicitly retain `dirty=true`; rebuild from committed code before
using artifacts for reported research. No database connection or model training is
required. Generated feature files and manifests are ignored by Git under `data/`.

Running the same command regenerates the same partitions. File writes use temporary
files and atomic replacement. This protects individual files, not a whole multi-file
build transaction: verify the manifest hashes before consuming an interrupted build,
and rerun it to completion. Unexpected old year partitions are refused rather than
silently included or deleted; review them before rebuilding. Missing coins are reported
and cause a nonzero exit code while other requested coins can still complete.

The export does not evaluate alphas or consume TEST-access budgets. Any later evaluation
must enforce its split, label, embargo and holdout-access policies before using these
features.

## BTC visual inspection (step 084)

`research/notebooks/01_feature_check.ipynb` checks the stored BTC hourly features
against source bars using only the configured H-HOURLY TRAIN period. From the
repository root in WSL, use the external environment documented for this project:

```bash
export UV_PROJECT_ENVIRONMENT=/home/abhi/.venvs/helios
uv sync --group notebooks
```

Open the notebook in a notebook editor, select that environment's Python kernel,
and Run All. The `notebooks` dependency group contains the plotting, kernel and
execution tools; it is separate from the default development dependencies. The
default figures cover January 2021 and a February 2018 data gap. Both windows are
checked against TRAIN boundaries. Source and feature partition hashes, timestamp
alignment, mask/NaN consistency, nonnegative volatility and taker-ratio bounds are
checked before plotting. The notebook displays the original build lineage and
feature units/lookbacks; it does not rebuild the store or read labels.

For a reproducible headless execution from the repository root:

```bash
MPLBACKEND=module://matplotlib_inline.backend_inline uv run --group notebooks python - <<'PY'
from pathlib import Path
import nbformat
from nbclient import NotebookClient

source = Path("research/notebooks/01_feature_check.ipynb").resolve()
notebook = nbformat.read(source, as_version=4)
nbformat.validate(notebook)
NotebookClient(
    notebook, timeout=180, kernel_name="python3",
    resources={"metadata": {"path": str(source.parent)}},
).execute()
output = Path("reports_out/feature_check/01_feature_check.executed.ipynb")
output.parent.mkdir(parents=True, exist_ok=True)
nbformat.write(notebook, output)
PY
```

The notebook writes `btc_features.png` and `btc_availability.png` under ignored
`reports_out/feature_check/`. Keep tracked notebook outputs cleared so stored
observations cannot silently become stale. Missing hours remain gaps in plots;
off-grid rows are counted without rounding their timestamps or filling data.

On 2026-10-09, all four code cells executed successfully against the clean
`255edd714a1194a3dbd2a2d46f13806fd5d5864f` feature build: five source/feature
partition pairs verified, 43,705 TRAIN rows inspected. Visual review found mean
distance and returns consistent with the displayed price movements, nonnegative
volatility reacting to larger moves, volume bursts visible in z-scores, and taker
fractions within bounds. The gap view showed 75 missing hourly timestamps and
43 off-grid stored rows, with longer lookbacks recovering later. These are data
sanity observations, not evidence of predictive value or trading performance.
