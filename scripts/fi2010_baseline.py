"""Run the FI-2010 baselines and save the results (steps 050, 063).

    uv run python scripts/fi2010_baseline.py                      # both models, seeds 0 1 2
    uv run python scripts/fi2010_baseline.py --model mlp --seeds 0
    uv run python scripts/fi2010_baseline.py --horizon 50

Results go to reports_out/, which git ignores: every number here comes from a run that
records its own commit and config hash, so results are reproduced, never copied by hand.
`scripts/fi2010_baselines_report.py` turns those files into the document.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from helios.ml.baselines import (
    LogisticBaselineConfig,
    MLPBaselineConfig,
    run_baseline,
    summarise,
)
from helios.ml.fi2010 import DEFAULT_ZIP, LABEL_HORIZONS, load_split

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "reports_out"
MODELS = ("logreg", "mlp")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=[*MODELS, "both"], default="both")
    parser.add_argument("--horizon", type=int, default=10, choices=LABEL_HORIZONS)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if not DEFAULT_ZIP.is_file():
        print(f"error: FI-2010 dataset not found at {DEFAULT_ZIP}", file=sys.stderr)
        return 2

    print("loading FI-2010 (this reads ~940 MB of text, about 25 s) ...", flush=True)
    split = load_split()
    print(
        f"train {split.train.n_events:,} | val {split.val.n_events:,} "
        f"| test {split.test.n_events:,}",
        flush=True,
    )

    wanted = MODELS if args.model == "both" else (args.model,)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    everything = []

    for name in wanted:
        config = (
            LogisticBaselineConfig(horizon=args.horizon)
            if name == "logreg"
            else MLPBaselineConfig(horizon=args.horizon)
        )
        print(f"\n--- {config.model}, seeds {args.seeds} ---", flush=True)
        results = run_baseline(split, config, seeds=args.seeds)
        out_file = args.out_dir / f"fi2010_{name}_k{args.horizon}.csv"
        results.to_csv(out_file, index=False)
        everything.append(results)

        shown = ["seed", "accuracy", "macro_f1", "majority_accuracy", "fit_seconds"]
        print(results[shown].to_string(index=False))
        print(f"saved: {out_file}")

    print("\n--- mean and spread across seeds ---")
    print(summarise(pd.concat(everything, ignore_index=True)).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
