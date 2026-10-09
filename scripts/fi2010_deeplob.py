"""One seeded DeepLOB TRAIN smoke epoch; outputs are development diagnostics, not test scores."""

import argparse
import hashlib
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import torch

from helios.common.lineage import RunContext
from helios.ml.deeplob_training import (
    DeepLOBTrainingConfig,
    load_training_windows,
    train_deeplob,
)
from helios.ml.fi2010 import DEFAULT_ZIP, TRAIN_FILE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--out-dir", type=Path, default=Path("reports_out/deeplob"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--max-windows", type=int, default=1024)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args(argv)
    config = DeepLOBTrainingConfig(
        seed=args.seed,
        epochs=args.epochs,
        max_windows=args.max_windows,
        batch_size=args.batch_size,
        device=args.device,
    )
    with args.zip.open("rb") as stream:
        snapshot = hashlib.file_digest(stream, "sha256").hexdigest()
    lineage = RunContext.capture(config, "sha256:" + snapshot, config.seed)
    print(f"Loading {TRAIN_FILE}; TEST members will not be read.", flush=True)
    dataset, source_events, cutoff = load_training_windows(config, args.zip)
    print(
        f"Training {len(dataset)} chronological windows on {config.device}, seed={config.seed}.",
        flush=True,
    )
    started = time.perf_counter()
    model, metrics = train_deeplob(dataset, config)
    fit_seconds = time.perf_counter() - started
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    destination = args.out_dir / run_id
    destination.mkdir(parents=True, exist_ok=False)
    checkpoint = destination / "model.pt"
    torch.save(
        {
            "state_dict": model.cpu().state_dict(),
            "normalization_mean": dataset.mean,
            "normalization_std": dataset.std,
            "config": config.model_dump(mode="json"),
        },
        checkpoint,
    )
    with checkpoint.open("rb") as stream:
        checkpoint_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {
        "purpose": "TRAIN smoke diagnostic; not a held-out benchmark result",
        "config": config.model_dump(mode="json"),
        "lineage": asdict(lineage) | {"created_at": lineage.created_at.isoformat()},
        "source": {
            "archive_sha256": snapshot,
            "member": TRAIN_FILE,
            "events": source_events,
            "train_cutoff_exclusive": cutoff,
            "input_events": dataset.input_events,
            "last_endpoint": dataset.last_endpoint,
            "last_label_future_endpoint": dataset.last_endpoint + config.horizon,
        },
        "metrics": asdict(metrics) | {"loss_decreased": metrics.loss_decreased},
        "fit_seconds": fit_seconds,
        "torch_version": str(torch.__version__),
        "checkpoint": {"path": "model.pt", "sha256": checkpoint_hash},
    }
    with (destination / "smoke.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"TRAIN eval loss: {metrics.loss_before:.6f} -> {metrics.loss_after:.6f}")
    print(f"loss_decreased={metrics.loss_decreased}; saved {destination}")
    return 0 if metrics.loss_decreased else 1


if __name__ == "__main__":
    raise SystemExit(main())
