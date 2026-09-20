"""Run the FI-2010 logistic-regression baseline and save the results (step 050).

    uv run python scripts/fi2010_baseline.py                  # seeds 0 1 2, horizon 10
    uv run python scripts/fi2010_baseline.py --horizon 50 --seeds 0

Results go to reports_out/, which git ignores: every number here comes from a run that
records its own commit and config hash, so results are reproduced, never copied by hand.
"""

import argparse
import sys
from pathlib import Path

from helios.ml.baselines import LogisticBaselineConfig, run_logistic_baseline
from helios.ml.fi2010 import DEFAULT_ZIP, LABEL_HORIZONS, load_split

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "reports_out"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon", type=int, default=10, choices=LABEL_HORIZONS)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--max-iter", type=int, default=200)
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

    config = LogisticBaselineConfig(horizon=args.horizon, max_iter=args.max_iter)
    results = run_logistic_baseline(split, config, seeds=args.seeds)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_file = args.out_dir / f"fi2010_logreg_k{args.horizon}.csv"
    results.to_csv(out_file, index=False)

    shown = ["seed", "accuracy", "macro_f1", "majority_accuracy", "fit_seconds"]
    print(results[shown].to_string(index=False))
    print(f"saved: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
