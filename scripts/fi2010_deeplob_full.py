"""Three fixed-seed full TRAIN runs, with held-out VALID scores and external checkpoints."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import torch

from helios.common.config import config_hash
from helios.ml.deeplob_evaluation import HoldoutWindows, evaluate_classifier
from helios.ml.deeplob_training import DeepLOBTrainingConfig, LOBWindowDataset, train_deeplob
from helios.ml.fi2010 import DEFAULT_ZIP, TRAIN_FILE, load


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--out-dir", type=Path, default=Path("reports_out/deeplob_full"))
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--source-manifest", type=Path)
    args = parser.parse_args(argv)
    # Must be set before the first CUDA BLAS operation; deterministic failures stay errors.
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    configs = [
        DeepLOBTrainingConfig(
            seed=seed,
            epochs=args.epochs,
            batch_size=args.batch_size,
            device=args.device,
            max_windows=None,
        )
        for seed in (0, 1, 2)
    ]
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("full GPU training requires an available CUDA device")
    if args.source_manifest:
        source = json.loads(args.source_manifest.read_text(encoding="utf-8"))
        for name, expected in source["files"].items():
            if file_hash(Path(name)) != expected:
                raise RuntimeError(f"source checksum mismatch: {name}")
        source["manifest_sha256"] = file_hash(args.source_manifest)
    else:
        source = {
            "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
        }
    destination = args.out_dir / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    )
    destination.mkdir(parents=True, exist_ok=False)
    snapshot = file_hash(args.zip)
    protocol = {
        "purpose": "Full eligible TRAIN windows; held-out VALID classification; TEST untouched",
        "seeds": [0, 1, 2],
        "configs": [c.model_dump(mode="json") for c in configs],
        "source": source,
        "archive_sha256": snapshot,
        "train_member": TRAIN_FILE,
        "evaluation_split": "valid",
        "selection": "fixed final epoch; no seed retries or selection",
        "torch_version": str(torch.__version__),
        "python_version": platform.python_version(),
        "gpu": torch.cuda.get_device_name(0) if args.device == "cuda" else None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    (destination / "protocol.json").write_text(
        json.dumps(protocol, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(f"Protocol saved before training: {destination}", flush=True)
    data = load(TRAIN_FILE, args.zip)  # never parses days 8–10
    cut = int(data.n_events * (1 - configs[0].val_fraction))
    training = LOBWindowDataset(data.lob[:cut], data.labels_for(10)[:cut], 10)
    validation = HoldoutWindows(data.lob[cut:], data.labels_for(10)[cut:], training)
    del data
    for config in configs:
        print(
            f"Seed {config.seed}: {len(training)} TRAIN / {len(validation)} VALID windows",
            flush=True,
        )
        started = time.perf_counter()
        model, loss = train_deeplob(
            training,
            config,
            progress=lambda epoch, value: print(
                f"epoch {epoch}: train loss {value:.6f}", flush=True
            ),
        )
        fit_seconds = time.perf_counter() - started
        score = evaluate_classifier(
            model, validation, batch_size=config.batch_size, device=config.device
        )
        checkpoint = destination / f"seed_{config.seed}.pt"
        torch.save(
            {
                "state_dict": model.cpu().state_dict(),
                "normalization_mean": training.mean,
                "normalization_std": training.std,
                "config": config.model_dump(mode="json"),
            },
            checkpoint,
        )
        report = {
            "seed": config.seed,
            "config_hash": config_hash(config),
            "config": config.model_dump(mode="json"),
            "archive_sha256": snapshot,
            "source": source,
            "train_cutoff_exclusive": cut,
            "last_train_label_future_endpoint": training.last_endpoint + 10,
            "evaluation_split": "valid",
            "classification": asdict(score),
            "train_loss": asdict(loss),
            "fit_seconds": fit_seconds,
            "checkpoint_sha256": file_hash(checkpoint),
            "protocol_sha256": file_hash(destination / "protocol.json"),
        }
        (destination / f"seed_{config.seed}.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        print(
            f"seed={config.seed} VALID accuracy={score.accuracy:.6f} macro-F1={score.macro_f1:.6f}",
            flush=True,
        )
        del model
        if config.device == "cuda":
            torch.cuda.empty_cache()
    print(f"All three seeds completed: {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
