"""Purged held-out windows with TRAIN-only normalization; accuracy and macro-F1."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import torch
from torch import Tensor, nn
from torch.utils.data import DataLoader, Dataset

from helios.ml.deeplob import FEATURES, SNAPSHOTS
from helios.ml.deeplob_training import DeepLOBTrainingError, LOBWindowDataset


class HoldoutWindows(Dataset[tuple[Tensor, Tensor]]):
    """Start history within the holdout and purge endpoints whose label extends beyond it."""

    def __init__(
        self,
        lob: npt.NDArray[np.float64],
        labels: npt.NDArray[np.int8],
        training: LOBWindowDataset,
    ) -> None:
        if lob.ndim != 2 or lob.shape[1] != FEATURES or labels.shape != (len(lob),):
            raise DeepLOBTrainingError("invalid holdout shapes")
        if not np.isfinite(lob).all() or not np.isin(labels, [1, 2, 3]).all():
            raise DeepLOBTrainingError("holdout must be finite with labels 1/2/3")
        self.n_windows = len(lob) - SNAPSHOTS + 1 - training.horizon
        if self.n_windows < 1:
            raise DeepLOBTrainingError("holdout too short for windows and horizon purge")
        with np.errstate(over="ignore", invalid="ignore"):
            values = ((lob - training.mean.numpy()) / training.std.numpy()).astype(np.float32)
        if not np.isfinite(values).all():
            raise DeepLOBTrainingError("non-finite holdout normalization")
        self.lob = torch.from_numpy(np.ascontiguousarray(values))
        self.labels = torch.tensor(
            labels[SNAPSHOTS - 1 : SNAPSHOTS - 1 + self.n_windows].astype(np.int64) - 1
        )

    def __len__(self) -> int:
        return self.n_windows

    def __getitem__(self, index: int) -> tuple[Tensor, Tensor]:
        if not 0 <= index < self.n_windows:
            raise IndexError(index)
        return self.lob[index : index + SNAPSHOTS].unsqueeze(0), self.labels[index]


@dataclass(frozen=True)
class ClassificationMetrics:
    n_windows: int
    accuracy: float
    macro_f1: float
    confusion_matrix: tuple[tuple[int, ...], ...]


def classification_metrics(confusion: npt.NDArray[np.int64]) -> ClassificationMetrics:
    """Rows are true classes, columns predictions; include all three classes in macro-F1."""
    if confusion.shape != (3, 3) or not np.issubdtype(confusion.dtype, np.integer):
        raise DeepLOBTrainingError("confusion matrix must be 3x3 integers")
    if (confusion < 0).any() or int(confusion.sum()) < 1:
        raise DeepLOBTrainingError("confusion counts must be non-negative and non-empty")
    diagonal = confusion.diagonal().astype(float)
    denominator = confusion.sum(axis=0) + confusion.sum(axis=1)
    f1 = np.divide(2 * diagonal, denominator, out=np.zeros(3), where=denominator != 0)
    count = int(confusion.sum())
    return ClassificationMetrics(
        count,
        float(diagonal.sum() / count),
        float(f1.mean()),
        tuple(tuple(int(value) for value in row) for row in confusion),
    )


def evaluate_classifier(
    model: nn.Module, dataset: HoldoutWindows, *, batch_size: int = 32, device: str = "cpu"
) -> ClassificationMetrics:
    if isinstance(batch_size, bool) or batch_size < 1:
        raise DeepLOBTrainingError("batch size must be positive")
    was_training = model.training
    confusion = np.zeros((3, 3), dtype=np.int64)
    try:
        model.eval()
        with torch.no_grad():
            for inputs, labels in DataLoader(dataset, batch_size=batch_size, shuffle=False):
                logits = model(inputs.to(device))
                if logits.shape != (len(labels), 3) or not torch.isfinite(logits).all():
                    raise DeepLOBTrainingError("invalid classifier output")
                predicted = logits.argmax(dim=1).cpu().numpy()
                confusion += np.bincount(labels.numpy() * 3 + predicted, minlength=9).reshape(3, 3)
    finally:
        model.train(was_training)
    return classification_metrics(confusion)
