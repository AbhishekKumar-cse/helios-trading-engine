"""Chronology, endpoint labels, reproducibility and artifact tests for step 087."""

import hashlib
import io
import json
import math
import runpy
import zipfile
from pathlib import Path

import numpy as np
import pytest
import torch
from pydantic import ValidationError

from helios.common.seed import set_seed
from helios.ml.deeplob import SNAPSHOTS, DeepLOB
from helios.ml.deeplob_training import (
    DeepLOBTrainingConfig,
    DeepLOBTrainingError,
    LOBWindowDataset,
    load_training_windows,
    train_deeplob,
)
from helios.ml.fi2010 import TRAIN_FILE


def arrays(n: int = 160) -> tuple[np.ndarray, np.ndarray]:
    lob = np.random.default_rng(42).normal(size=(n, 40))
    labels = (np.arange(n) % 3 + 1).astype(np.int8)
    return lob, labels


def write_train_zip(path: Path, n: int = 160) -> None:
    lob, labels = arrays(n)
    matrix = np.zeros((149, n))
    matrix[:40] = lob.T
    matrix[-5:] = labels
    text = io.StringIO()
    np.savetxt(text, matrix)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(TRAIN_FILE, text.getvalue())  # deliberately no TEST members


def test_window_uses_past_snapshots_and_label_at_its_endpoint() -> None:
    lob, labels = arrays()
    dataset = LOBWindowDataset(lob, labels, horizon=10)
    for index in [0, 1, len(dataset) - 1]:
        inputs, target = dataset[index]
        recovered = inputs[0].numpy() * dataset.std.numpy() + dataset.mean.numpy()
        np.testing.assert_allclose(recovered, lob[index : index + SNAPSHOTS], atol=1e-6)
        assert inputs.shape == (1, 100, 40)
        assert inputs.dtype == torch.float32
        assert target.item() == labels[index + SNAPSHOTS - 1] - 1
        assert target.dtype == torch.long
    assert dataset.last_endpoint + 10 < len(lob)
    assert len(dataset) == len(lob) - 100 + 1 - 10


def test_normalization_fits_only_selected_training_events() -> None:
    lob, labels = arrays()
    first = LOBWindowDataset(lob, labels, 10, max_windows=8)
    changed = lob.copy()
    changed[first.input_events :] = 1e6
    second = LOBWindowDataset(changed, labels, 10, max_windows=8)
    assert torch.equal(first.mean, second.mean)
    assert torch.equal(first.std, second.std)
    assert torch.equal(first.lob, second.lob)


def test_constant_columns_and_small_final_batch_are_supported() -> None:
    lob, labels = arrays()
    lob[:, 0] = 42
    dataset = LOBWindowDataset(lob, labels, 10, max_windows=5)
    assert dataset.std[0].item() == 1
    assert (dataset.lob[:, 0] == 0).all()
    _, metrics = train_deeplob(dataset, DeepLOBTrainingConfig(max_windows=5, batch_size=4))
    assert metrics.optimizer_steps == 2
    assert math.isfinite(metrics.loss_after)


def test_loader_reserves_validation_and_never_requires_test_members(tmp_path: Path) -> None:
    archive = tmp_path / "train_only.zip"
    write_train_zip(archive, n=250)
    dataset, source_events, cut = load_training_windows(
        DeepLOBTrainingConfig(max_windows=None), archive
    )
    assert (source_events, cut) == (250, 200)
    assert dataset.last_endpoint + dataset.horizon == cut - 1


@pytest.mark.parametrize(
    "changes",
    [
        {"seed": True},
        {"seed": -1},
        {"epochs": 0},
        {"batch_size": 0},
        {"max_windows": 0},
        {"val_fraction": 1},
        {"horizon": 11},
        {"learning_rate": math.inf},
        {"learning_rate": math.nan},
        {"torch_threads": 0},
        {"shuffle": True},
        {"snapshots": 50},
    ],
)
def test_invalid_config_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DeepLOBTrainingConfig.model_validate(changes)


def test_dataset_rejects_bad_shapes_labels_and_insufficient_purged_history() -> None:
    lob, labels = arrays()
    for bad_lob, bad_labels in [
        (lob[:, :39], labels),
        (lob, labels[:-1]),
        (lob[:100], labels[:100]),
        (lob, labels * 0),
    ]:
        with pytest.raises(DeepLOBTrainingError):
            LOBWindowDataset(bad_lob, bad_labels, 10)
    lob[0, 0] = np.nan
    with pytest.raises(DeepLOBTrainingError, match="finite"):
        LOBWindowDataset(lob, labels, 10)


def test_dataset_indexes_are_checked() -> None:
    dataset = LOBWindowDataset(*arrays(), horizon=10)
    for index in [-1, len(dataset)]:
        with pytest.raises(IndexError):
            dataset[index]


def test_training_updates_weights_and_repeats_exactly_for_fixed_seed() -> None:
    config = DeepLOBTrainingConfig(max_windows=8, batch_size=4)
    dataset = LOBWindowDataset(*arrays(), horizon=10, max_windows=8)
    set_seed(config.seed)
    initial = DeepLOB().state_dict()
    previous_threads = torch.get_num_threads()
    previous_deterministic = torch.are_deterministic_algorithms_enabled()
    first_model, first = train_deeplob(dataset, config)
    second_model, second = train_deeplob(dataset, config)
    assert first == second
    assert first.optimizer_steps == 2
    assert len(first.epoch_losses) == 1
    assert first.n_windows == 8
    assert first.loss_decreased == (first.loss_after < first.loss_before)
    assert any(not torch.equal(initial[k], v) for k, v in first_model.state_dict().items())
    assert all(
        torch.equal(v, second_model.state_dict()[k]) for k, v in first_model.state_dict().items()
    )
    assert torch.get_num_threads() == previous_threads
    assert torch.are_deterministic_algorithms_enabled() == previous_deterministic


def test_horizon_mismatch_and_unavailable_gpu_fail_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = LOBWindowDataset(*arrays(), horizon=10, max_windows=1)
    with pytest.raises(DeepLOBTrainingError, match="horizons differ"):
        train_deeplob(dataset, DeepLOBTrainingConfig(horizon=20))
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(DeepLOBTrainingError, match="unavailable"):
        train_deeplob(dataset, DeepLOBTrainingConfig(device="cuda"))


def test_nonfinite_model_output_fails_and_restores_runtime_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_forward(self: DeepLOB, inputs: torch.Tensor) -> torch.Tensor:
        return torch.full((len(inputs), 3), float("nan"))

    monkeypatch.setattr(DeepLOB, "forward", invalid_forward)
    before_threads = torch.get_num_threads()
    before_determinism = torch.are_deterministic_algorithms_enabled()
    dataset = LOBWindowDataset(*arrays(), horizon=10, max_windows=1)
    with pytest.raises(DeepLOBTrainingError, match="non-finite evaluation loss"):
        train_deeplob(dataset, DeepLOBTrainingConfig())
    assert torch.get_num_threads() == before_threads
    assert torch.are_deterministic_algorithms_enabled() == before_determinism


def test_cli_artifacts_have_lineage_checkpoint_hash_and_no_overwrite(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    write_train_zip(archive)
    output = tmp_path / "runs"
    root = Path(__file__).resolve().parents[2]
    main = runpy.run_path(str(root / "scripts/fi2010_deeplob.py"))["main"]
    args = ["--zip", str(archive), "--out-dir", str(output), "--max-windows", "4"]
    statuses = [main(args), main(args)]
    destinations = sorted(output.iterdir())
    assert len(destinations) == 2
    for destination, status in zip(destinations, statuses, strict=True):
        report = json.loads((destination / "smoke.json").read_text())
        assert report["source"]["member"] == TRAIN_FILE
        assert (
            report["source"]["last_label_future_endpoint"]
            < report["source"]["train_cutoff_exclusive"]
        )
        assert len(report["lineage"]["code_commit"]) == 40
        assert len(report["lineage"]["config_hash"]) == 64
        assert report["lineage"]["seed"] == 0
        assert status == (0 if report["metrics"]["loss_decreased"] else 1)
        checkpoint = destination / "model.pt"
        assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == report["checkpoint"]["sha256"]
        stored = torch.load(checkpoint, weights_only=True)
        assert "state_dict" in stored and "normalization_mean" in stored
        assert "accuracy" not in report["metrics"]
