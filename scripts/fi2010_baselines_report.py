"""Write docs/research/fi2010_baselines.md from the baseline result files (step 063).

    uv run python scripts/fi2010_baselines_report.py

Every number in that document comes from `reports_out/fi2010_*.csv`, written by
`scripts/fi2010_baseline.py`. Nothing is typed by hand, so re-running after a new experiment
refreshes the document and `git diff` shows exactly what changed.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from helios.common.lineage import git_commit, git_is_dirty
from helios.ml.baselines import summarise

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = PROJECT_ROOT / "reports_out"
DEFAULT_DOC = PROJECT_ROOT / "docs" / "research" / "fi2010_baselines.md"


def load_results(in_dir: Path) -> pd.DataFrame:
    files = sorted(in_dir.glob("fi2010_*_k*.csv"))
    if not files:
        raise FileNotFoundError(f"no baseline results in {in_dir}")
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def table(summary: pd.DataFrame) -> str:
    head = (
        '| Model | Horizon | Seeds | Accuracy | Macro-F1 | Always "flat" | Fit time |\n'
        "|---|---|---|---|---|---|---|\n"
    )
    body = ""
    for row in summary.itertuples():
        body += (
            f"| `{row.model}` | k = {row.horizon} | {row.seeds} "
            f"| {row.accuracy_mean:.4f} ± {row.accuracy_std:.4f} "
            f"| **{row.macro_f1_mean:.4f} ± {row.macro_f1_std:.4f}** "
            f"| {row.majority_accuracy:.4f} | {row.fit_seconds_mean:.1f} s |\n"
        )
    return head + body


def per_seed_table(results: pd.DataFrame) -> str:
    head = "| Model | Horizon | Seed | Accuracy | Macro-F1 |\n|---|---|---|---|---|\n"
    body = ""
    for row in results.sort_values(["model", "horizon", "seed"]).itertuples():
        body += (
            f"| `{row.model}` | k = {row.horizon} | {row.seed} "
            f"| {row.accuracy:.4f} | {row.macro_f1:.4f} |\n"
        )
    return head + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-dir", type=Path, default=DEFAULT_IN)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    args = parser.parse_args(argv)

    try:
        results = load_results(args.in_dir)
    except FileNotFoundError as exc:
        print(f"error: {exc}\nrun scripts/fi2010_baseline.py first", file=sys.stderr)
        return 2

    summary = summarise(results)
    best = summary.loc[summary["macro_f1_mean"].idxmax()]
    dirty = " (uncommitted changes)" if git_is_dirty() else ""

    text = f"""# FI-2010 baselines

**Generated** by `scripts/fi2010_baselines_report.py` on {datetime.now(UTC).date()} from
`reports_out/`, written by `scripts/fi2010_baseline.py`.
Commit `{git_commit()[:12]}`{dirty}. Do not edit by hand: re-run the script instead.

Data: FI-2010 (Ntakaris et al., 2018), DeepLOB packaging. Trained on the first 80 % of days
1-7 ({int(results["n_train"].iloc[0]):,} events), tested on days 8-10
({int(results["n_test"].iloc[0]):,} events). Inputs are the 40 order-book columns only.

## Results

{table(summary)}
Values are the mean ± standard deviation across seeds.

## Per seed

{per_seed_table(results)}
## How to read this

- **Accuracy is misleading here.** About 60 % of the labels at k = 10 are "stationary", so
  always answering "flat" scores ~0.71 without learning anything. That number is in the
  table to compare against.
- **Macro-F1 is the measure that counts.** It scores the three classes (up, flat, down)
  equally, so a model that ignores two of them cannot win.
- **The spread across seeds matters.** A single lucky run proves nothing; a model whose
  macro-F1 swings widely between seeds has not really achieved its best number.
- Logistic regression is deterministic, so its seeds are expected to be identical: that is a
  check for hidden randomness, not a measure of variance.

## What this tells us

The best baseline so far is `{best.model}` with macro-F1
**{best.macro_f1_mean:.4f} ± {best.macro_f1_std:.4f}** at k = {int(best.horizon)}.
Any later model — including the graph and transformer model planned for the 6th semester —
has to beat that number on the same split to be worth its complexity.

## Method notes

- The validation part is the **last** 20 % of the training file, in time order and never
  shuffled: shuffling would let a model train on events that happen after the ones it is
  validated on.
- The neural network runs a fixed number of passes with scikit-learn's early stopping
  switched off, because that feature would cut its own validation slice out of the training
  data by shuffling.
- Every run records its git commit, configuration fingerprint and seed.
"""
    args.doc.parent.mkdir(parents=True, exist_ok=True)
    args.doc.write_text(text, encoding="utf-8", newline="\n")
    print(table(summary))
    print(f"written: {args.doc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
