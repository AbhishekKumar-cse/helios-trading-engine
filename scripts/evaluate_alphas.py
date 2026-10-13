"""Evaluate registered alphas against a preregistered experiment in isolated processes."""

import argparse
import json
from dataclasses import asdict

from helios.registry.results import Split
from helios.sim.evaluate import EvaluationConfig
from helios.sim.many import EvaluationRequest, evaluate_many


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", type=int, required=True)
    parser.add_argument(
        "--alphas", nargs="+", default=["baseline_b0", "baseline_b1", "baseline_b2"]
    )
    parser.add_argument("--splits", nargs="+", choices=[s.value for s in Split], default=["valid"])
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--warmup-rows", type=int, default=168)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--actor", default="")
    parser.add_argument("--purpose", default="")
    args = parser.parse_args()
    config = EvaluationConfig(symbol=args.symbol, warmup_rows=args.warmup_rows)
    requests = [
        EvaluationRequest(alpha, Split(split), args.experiment_id, config, args.actor, args.purpose)
        for alpha in args.alphas
        for split in args.splits
    ]
    outcomes = evaluate_many(requests, workers=args.workers)
    for outcome in outcomes:
        print(json.dumps(asdict(outcome), sort_keys=True), flush=True)
    return int(any(outcome.error is not None for outcome in outcomes))


if __name__ == "__main__":
    raise SystemExit(main())
