"""Seeded DeepLOB training on past-only FI-2010 windows (step 087).

The default is a bounded one-epoch TRAIN smoke run, not a benchmark evaluation.
No validation/test events are used to fit normalization or to train the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt
import torch
from pydantic import Field, StrictInt
from torch import Tensor, nn
from torch.utils.data import DataLoader, Dataset

from helios.common.config import HeliosConfig
from helios.common.seed import MAX_SEED, set_seed
from helios.ml.deeplob import FEATURES, SNAPSHOTS, DeepLOB
from helios.ml.fi2010 import DEFAULT_ZIP, TRAIN_FILE, load


class DeepLOBTrainingError(Exception):
    """Invalid training data, unavailable device or non-finite optimization."""


class DeepLOBTrainingConfig(HeliosConfig):
    """All choices affecting the run are captured in its config fingerprint."""

    horizon: Literal[10, 20, 30, 50, 100] = 10
    seed: StrictInt = Field(default=0, ge=0, le=MAX_SEED)
    epochs: StrictInt = Field(default=1, ge=1)
    batch_size: StrictInt = Field(default=32, ge=1)
    learning_rate: float = Field(default=1e-3, gt=0, allow_inf_nan=False)
    max_windows: StrictInt | None = Field(default=1024, ge=1)
    val_fraction: float = Field(default=0.2, gt=0, lt=1, allow_inf_nan=False)
    device: Literal["cpu", "cuda"] = "cpu"
    torch_threads: StrictInt = Field(default=2, ge=1)
    snapshots: Literal[100] = 100
    shuffle: Literal[False] = False
    deterministic: Literal[True] = True


class LOBWindowDataset(Dataset[tuple[Tensor, Tensor]]):
    """A window ends at t and uses label[t]; final k endpoints are purged.

    Normalization is fitted only to the selected training prefix, not to the unused
    tail or any holdout. Store events once rather than materializing overlapping
    windows. Label encoding 1/2/3 becomes CrossEntropyLoss class index 0/1/2.
    """

    def __init__(
        self,
        lob: npt.NDArray[np.float64],
        labels: npt.NDArray[np.int8],
        horizon: int,
        max_windows: int | None = None,
    ) -> None:
        if lob.ndim != 2 or lob.shape[1] != FEATURES:
            raise DeepLOBTrainingError(f"LOB must have shape (events, {FEATURES})")
        if labels.ndim != 1 or len(labels) != len(lob):
            raise DeepLOBTrainingError("one label is required per LOB event")
        if not np.isfinite(lob).all() or not np.isin(labels, [1, 2, 3]).all():
            raise DeepLOBTrainingError("LOB must be finite and labels must be 1, 2 or 3")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
            raise DeepLOBTrainingError("horizon must be a positive integer")
        if max_windows is not None and (
            isinstance(max_windows, bool) or not isinstance(max_windows, int) or max_windows < 1
        ):
            raise DeepLOBTrainingError("max_windows must be a positive integer or None")
        available = len(lob) - SNAPSHOTS + 1 - horizon
        if available < 1:
            raise DeepLOBTrainingError("not enough TRAIN events for a window plus label horizon")
        self.n_windows = available if max_windows is None else min(available, max_windows)
        self.horizon = horizon
        self.input_events = SNAPSHOTS + self.n_windows - 1
        self.last_endpoint = self.input_events - 1
        selected = lob[: self.input_events]
        mean = selected.mean(axis=0)
        std = selected.std(axis=0)
        std = np.where(std > 0, std, 1.0)
        normalized = ((selected - mean) / std).astype(np.float32)
        if not np.isfinite(normalized).all():
            raise DeepLOBTrainingError("normalization produced non-finite inputs")
        self.mean = torch.tensor(mean, dtype=torch.float64)
        self.std = torch.tensor(std, dtype=torch.float64)
        self.lob = torch.from_numpy(np.ascontiguousarray(normalized))
        self.labels = torch.tensor(
            labels[SNAPSHOTS - 1 : self.input_events].astype(np.int64) - 1, dtype=torch.long
        )

    def __len__(self) -> int:
        return self.n_windows

    def __getitem__(self, index: int) -> tuple[Tensor, Tensor]:
        if not 0 <= index < self.n_windows:
            raise IndexError(index)
        return self.lob[index : index + SNAPSHOTS].unsqueeze(0), self.labels[index]


def load_training_windows(
    config: DeepLOBTrainingConfig, zip_path: Path = DEFAULT_ZIP
) -> tuple[LOBWindowDataset, int, int]:
    """Read only days 1–7; reserve their last 20% (by default) in time order.

    Returns dataset, source event count and exclusive TRAIN cutoff. Do not call
    load_split here: that loader would read the test members unnecessarily.
    """
    data = load(TRAIN_FILE, zip_path)
    cut = int(data.n_events * (1 - config.val_fraction))
    return (
        LOBWindowDataset(
            data.lob[:cut],
            data.labels_for(config.horizon)[:cut],
            config.horizon,
            config.max_windows,
        ),
        data.n_events,
        cut,
    )


@dataclass(frozen=True)
class TrainingMetrics:
    """Before/after use the same examples, batch size and eval mode (including BatchNorm)."""

    loss_before: float
    loss_after: float
    epoch_losses: tuple[float, ...]
    optimizer_steps: int
    n_windows: int

    @property
    def loss_decreased(self) -> bool:
        return self.loss_after < self.loss_before


def _measure_loss(model: DeepLOB, loader: DataLoader[tuple[Tensor, Tensor]], device: str) -> float:
    model.eval()
    total = 0.0
    count = 0
    with torch.no_grad():
        for inputs, labels in loader:
            loss = nn.functional.cross_entropy(model(inputs.to(device)), labels.to(device))
            if not torch.isfinite(loss):
                raise DeepLOBTrainingError("non-finite evaluation loss")
            total += float(loss.item()) * len(labels)
            count += len(labels)
    return total / count


def train_deeplob(
    dataset: LOBWindowDataset, config: DeepLOBTrainingConfig
) -> tuple[DeepLOB, TrainingMetrics]:
    """Train every selected window once per epoch, deterministically and in order.

    CPU is the documented default. CUDA must be explicitly requested and available;
    deterministic-algorithm failures are not silently relaxed. No seed/loss retries.
    """
    if dataset.horizon != config.horizon:
        raise DeepLOBTrainingError("dataset and config label horizons differ")
    if config.device == "cuda" and not torch.cuda.is_available():
        raise DeepLOBTrainingError("CUDA was requested but is unavailable")
    previous_threads = torch.get_num_threads()
    previous_deterministic = torch.are_deterministic_algorithms_enabled()
    previous_warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    try:
        torch.set_num_threads(config.torch_threads)
        torch.use_deterministic_algorithms(True)
        set_seed(config.seed)
        model = DeepLOB().to(config.device)
        loader = DataLoader(dataset, batch_size=config.batch_size, shuffle=False, num_workers=0)
        before = _measure_loss(model, loader, config.device)
        optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
        losses: list[float] = []
        steps = 0
        for _ in range(config.epochs):
            model.train()
            total = 0.0
            count = 0
            for inputs, labels in loader:
                optimizer.zero_grad(set_to_none=True)
                loss = nn.functional.cross_entropy(
                    model(inputs.to(config.device)), labels.to(config.device)
                )
                if not torch.isfinite(loss):
                    raise DeepLOBTrainingError("non-finite training loss")
                loss.backward()  # type: ignore[no-untyped-call]  # PyTorch omits this signature
                if any(
                    p.grad is not None and not torch.isfinite(p.grad).all()
                    for p in model.parameters()
                ):
                    raise DeepLOBTrainingError("non-finite gradient")
                optimizer.step()
                total += float(loss.item()) * len(labels)
                count += len(labels)
                steps += 1
            losses.append(total / count)
        after = _measure_loss(model, loader, config.device)
        return model, TrainingMetrics(before, after, tuple(losses), steps, len(dataset))
    finally:
        torch.set_num_threads(previous_threads)
        torch.use_deterministic_algorithms(previous_deterministic, warn_only=previous_warn_only)
