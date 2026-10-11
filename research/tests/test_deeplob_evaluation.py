"""Holdout boundaries and train-only normalization, with exact classification examples."""

import json
import runpy
from pathlib import Path

import numpy as np
import pytest
import torch
from test_deeplob_training import arrays, write_train_zip
from torch import nn

from helios.ml.deeplob_evaluation import HoldoutWindows, classification_metrics, evaluate_classifier
from helios.ml.deeplob_training import DeepLOBTrainingError, LOBWindowDataset, TrainingMetrics


def test_holdout_uses_training_stats_and_purges_future_labels() -> None:
    lob, labels = arrays(400)
    train = LOBWindowDataset(lob[:200], labels[:200], 10)
    mean, std = train.mean.clone(), train.std.clone()
    holdout = HoldoutWindows(lob[200:] + 100, labels[200:], train)
    assert len(holdout) == 91
    first, target = holdout[0]
    np.testing.assert_allclose(
        first[0].numpy() * std.numpy() + mean.numpy(), lob[200:300] + 100, atol=1e-5
    )
    assert target.item() == labels[299] - 1
    assert holdout[len(holdout) - 1][1].item() == labels[389] - 1
    assert torch.equal(train.mean, mean) and torch.equal(train.std, std)
    changed = HoldoutWindows(lob[200:] - 100, labels[200:], train)
    assert not torch.equal(holdout.lob, changed.lob)
    for index in (-1, len(holdout)):
        with pytest.raises(IndexError):
            holdout[index]


def test_macro_f1_counts_absent_classes_as_zero() -> None:
    result = classification_metrics(np.diag([0, 12, 0]).astype(np.int64))
    assert result.accuracy == 1 and result.macro_f1 == pytest.approx(1 / 3)
    result = classification_metrics(np.array([[2, 1, 0], [0, 2, 1], [1, 0, 2]], dtype=np.int64))
    assert result.accuracy == result.macro_f1 == pytest.approx(2 / 3)


class FlatClassifier(nn.Module):
    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        result = torch.zeros(len(inputs), 3)
        result[:, 1] = 1
        return result


def test_batched_evaluation_counts_each_window_and_restores_mode() -> None:
    lob, labels = arrays()
    train = LOBWindowDataset(lob, labels, 10)
    holdout = HoldoutWindows(lob, labels, train)
    model = FlatClassifier()
    result = evaluate_classifier(model, holdout, batch_size=7)
    counts = np.bincount(holdout.labels.numpy(), minlength=3)
    assert result.n_windows == len(holdout) and model.training
    assert result.accuracy == pytest.approx(counts[1] / len(holdout))
    assert result.macro_f1 == pytest.approx((2 * counts[1] / (len(holdout) + counts[1])) / 3)
    assert [row[1] for row in result.confusion_matrix] == counts.tolist()


def test_invalid_holdout_data_and_classifier_output_rejected() -> None:
    lob, labels = arrays()
    train = LOBWindowDataset(lob, labels, 10)
    for invalid_lob, invalid_labels in [
        (lob[:100], labels[:100]),
        (lob[:, :39], labels),
        (lob, labels * 0),
    ]:
        with pytest.raises(DeepLOBTrainingError):
            HoldoutWindows(invalid_lob, invalid_labels, train)
    lob[0, 0] = np.nan
    with pytest.raises(DeepLOBTrainingError, match="finite"):
        HoldoutWindows(lob, labels, train)


@pytest.mark.parametrize(
    "matrix",
    [
        np.zeros((3, 3), dtype=np.int64),
        np.ones((2, 2), dtype=np.int64),
        -np.ones((3, 3), dtype=np.int64),
        np.ones((3, 3)),
    ],
)
def test_invalid_confusion_matrix_rejected(matrix: np.ndarray) -> None:
    with pytest.raises(DeepLOBTrainingError):
        classification_metrics(matrix)


def test_full_cli_records_all_seeds_and_never_needs_test_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "train_only.zip"
    write_train_zip(archive, 750)
    namespace = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/fi2010_deeplob_full.py")
    )
    main = namespace["main"]
    seeds: list[int] = []

    def trainer(dataset: LOBWindowDataset, config: object, **kwargs: object) -> tuple:
        assert config.max_windows is None
        seeds.append(config.seed)
        return FlatClassifier(), TrainingMetrics(1, 1, (1,), 1, len(dataset))

    monkeypatch.setitem(main.__globals__, "train_deeplob", trainer)
    destination = tmp_path / "runs"
    assert (
        main(
            [
                "--zip",
                str(archive),
                "--out-dir",
                str(destination),
                "--device",
                "cpu",
                "--epochs",
                "1",
            ]
        )
        == 0
    )
    assert seeds == [0, 1, 2]
    run = next(destination.iterdir())
    assert len(list(run.glob("*.pt"))) == 3
    for seed in seeds:
        report = json.loads((run / f"seed_{seed}.json").read_text())
        assert report["seed"] == seed and report["evaluation_split"] == "valid"
        assert report["train_loss"]["n_windows"] == 491
        assert report["last_train_label_future_endpoint"] == 599
        assert report["classification"]["n_windows"] == 41
        assert len(report["checkpoint_sha256"]) == len(report["protocol_sha256"]) == 64
