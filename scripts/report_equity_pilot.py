"""Verify serialized equity models against VALID predictions and publish a small summary.

No refit, registry writes, TEST observations, or price-data redistribution.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import Booster

from helios.common.config import load_config
from helios.common.lineage import PROJECT_ROOT
from helios.data.equities import EquityPilotConfig, sha256, write_json
from helios.ml.equity_pilot import features_for, load_inputs, sample_hash, split_samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prior-attempt", type=Path)
    args = parser.parse_args()
    run = args.run
    report = json.loads((run / "report.json").read_text())
    snapshot = Path(report["snapshot"])
    manifest = json.loads((snapshot / "manifest.json").read_text())
    config = load_config(run / "protocol.json", EquityPilotConfig)
    for source, digest in report["source_sha256"].items():
        if sha256(run / "source" / Path(source).name) != digest:
            raise ValueError("archived source mismatch")
        if sha256(PROJECT_ROOT / source) != digest:
            raise ValueError("current source differs; verify with the archived run source")
    if sha256(run / "feature_protocol.json") != report["feature_protocol_sha256"]:
        raise ValueError("feature protocol fingerprint mismatch")
    for interval in ("1d", "60m"):
        model_report = report["models"][interval]
        frames, _, digest = load_inputs(snapshot, config, interval)
        if digest != model_report["manifest_sha256"]:
            raise ValueError("input manifest changed")
        train, valid, _ = split_samples(frames, config, interval)
        if sample_hash(train, interval) != model_report["train_sample_sha256"]:
            raise ValueError("TRAIN sample hash mismatch")
        if sample_hash(valid, interval) != model_report["valid_sample_sha256"]:
            raise ValueError("VALID sample hash mismatch")
        model_path = run / f"lightgbm_{interval}.txt"
        predictions_path = run / f"valid_predictions_{interval}.parquet"
        if sha256(model_path) != model_report["model_sha256"]:
            raise ValueError("serialized model fingerprint mismatch")
        if sha256(predictions_path) != model_report["predictions_sha256"]:
            raise ValueError("predictions fingerprint mismatch")
        predictions = pd.read_parquet(predictions_path)
        np.testing.assert_array_equal(predictions["symbol"], valid["symbol"])
        np.testing.assert_array_equal(predictions["target"], valid["target"])
        reloaded = Booster(model_file=str(model_path)).predict(valid[list(features_for(interval))])
        np.testing.assert_allclose(reloaded, predictions["probability_up"], rtol=0, atol=1e-12)
    intervals = {}
    for interval in ("1d", "60m", "1m"):
        records = [record for record in manifest["files"] if record["interval"] == interval]
        intervals[interval] = dict(
            companies=len(records),
            bars=sum(record["retained_bars"] for record in records),
            first_session=min(record["first_session"] for record in records),
            last_session=max(record["last_session"] for record in records),
            partial_bars=sum(record["partial_bars"] for record in records),
            zero_volume_bars=sum(record["zero_volume_bars"] for record in records),
            excluded_rows=dict(
                sum((Counter(record["rejected_rows"]) for record in records), Counter())
            ),
        )
    summary = dict(
        status="VERIFIED_DEVELOPMENT_ONLY",
        run=str(run),
        snapshot=str(snapshot),
        manifest_sha256=sha256(snapshot / "manifest.json"),
        report_sha256=sha256(run / "report.json"),
        universe_source=manifest["universe_source"],
        provider=manifest["provider"],
        universe_sha256=manifest["universe_sha256"],
        intervals=intervals,
        config_hash=report["config_hash"],
        feature_protocol_sha256=report["feature_protocol_sha256"],
        source_sha256=report["source_sha256"],
        versions=report["versions"],
        test_observation_accesses=report["test_observation_accesses"],
        registry_writes=0,
        saved_models_reload_and_predictions_match=True,
        limitations=report["limitations"],
        prior_attempt=(
            dict(
                path=str(args.prior_attempt),
                failure_sha256=sha256(args.prior_attempt / "failure.json"),
                failure=json.loads((args.prior_attempt / "failure.json").read_text()),
            )
            if args.prior_attempt
            else None
        ),
        models={
            key: {name: value for name, value in model.items() if name != "snapshot_files"}
            for key, model in report["models"].items()
        },
        coverage=[
            {
                key: entry[key]
                for key in (
                    "symbol",
                    "interval",
                    "retained_bars",
                    "first_session",
                    "last_session",
                    "partial_bars",
                    "zero_volume_bars",
                    "rejected_rows",
                )
            }
            for entry in manifest["files"]
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, summary)
    print(
        json.dumps(
            {
                "summary": str(args.output),
                "coverage": intervals,
                "verification": "serialized models and all VALID predictions match",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
