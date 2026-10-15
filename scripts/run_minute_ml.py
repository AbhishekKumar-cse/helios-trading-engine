"""Consume one exact preregistered minute ML pipeline from clean source."""

import argparse

from helios.ml.minute_pipeline import run_minute_ml

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True, type=int)
    args = parser.parse_args()
    print(run_minute_ml(args.experiment_id))
