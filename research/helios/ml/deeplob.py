"""The DeepLOB model, as a skeleton (step 075).

DeepLOB (Zhang, Zohren and Roberts, 2019) predicts the direction of the mid-price from a
window of order-book snapshots. It is the published benchmark our own baselines exist to be
measured against: logistic regression reached macro-F1 0.281 and a small network 0.344 on
the same split (step 063), so this model has to beat 0.344 to be worth its complexity.

**Input** `(batch, 1, 100, 40)` — for each example, 100 consecutive order-book snapshots,
each of 40 numbers (10 levels x ask price, ask volume, bid price, bid volume).
**Output** `(batch, 3)` — one score per class: price up, flat, or down.

The shape of the network follows the paper:

| Stage | What it does |
|---|---|
| Convolution block 1 | pairs each price with its own volume (a 1x2 step of 2) |
| Convolution block 2 | pairs ask with bid at the same level |
| Convolution block 3 | reads across all 10 levels at once |
| Inception module | three views of the time axis (1, 3 and 5 steps) side by side |
| LSTM | reads the resulting sequence in order, keeping what matters |
| Linear | turns the final state into three scores |

Every convolution moves along time in one direction and never reads a later snapshot than
the one it is placed on, so the model cannot see its own future.

This step builds and shape-checks the network. Training it comes later; nothing here claims
any accuracy.
"""

from __future__ import annotations

import torch
from torch import Tensor, nn

SNAPSHOTS = 100  # time steps in one example
FEATURES = 40  # numbers per snapshot: 10 levels x (ask price, ask size, bid price, bid size)
CLASSES = 3  # up, flat, down
LEAK = 0.01  # slope of LeakyReLU below zero, as in the paper


class DeepLOBError(Exception):
    """Raised when the input does not have the shape the model needs."""


def _conv_block(
    in_channels: int, out_channels: int, first: tuple[int, int], stride: tuple[int, int] = (1, 1)
) -> nn.Sequential:
    """One convolution stage: a shaping step, then two passes along time."""
    return nn.Sequential(
        nn.Conv2d(in_channels, out_channels, first, stride=stride),
        nn.LeakyReLU(LEAK),
        nn.BatchNorm2d(out_channels),
        nn.Conv2d(out_channels, out_channels, (4, 1)),
        nn.LeakyReLU(LEAK),
        nn.BatchNorm2d(out_channels),
        nn.Conv2d(out_channels, out_channels, (4, 1)),
        nn.LeakyReLU(LEAK),
        nn.BatchNorm2d(out_channels),
    )


class Inception(nn.Module):
    """Three views of the same sequence, joined together.

    One branch looks at each moment on its own, one at three moments, one at five. Putting
    them side by side lets the next layer choose which timescale matters, instead of the
    architecture deciding in advance.
    """

    def __init__(self, in_channels: int, branch_channels: int = 64) -> None:
        super().__init__()
        self.one = nn.Sequential(
            nn.Conv2d(in_channels, branch_channels, (1, 1)),
            nn.LeakyReLU(LEAK),
            nn.BatchNorm2d(branch_channels),
            nn.Conv2d(branch_channels, branch_channels, (3, 1), padding=(1, 0)),
            nn.LeakyReLU(LEAK),
            nn.BatchNorm2d(branch_channels),
        )
        self.two = nn.Sequential(
            nn.Conv2d(in_channels, branch_channels, (1, 1)),
            nn.LeakyReLU(LEAK),
            nn.BatchNorm2d(branch_channels),
            nn.Conv2d(branch_channels, branch_channels, (5, 1), padding=(2, 0)),
            nn.LeakyReLU(LEAK),
            nn.BatchNorm2d(branch_channels),
        )
        self.three = nn.Sequential(
            nn.MaxPool2d((3, 1), stride=(1, 1), padding=(1, 0)),
            nn.Conv2d(in_channels, branch_channels, (1, 1)),
            nn.LeakyReLU(LEAK),
            nn.BatchNorm2d(branch_channels),
        )

    def forward(self, x: Tensor) -> Tensor:
        return torch.cat([self.one(x), self.two(x), self.three(x)], dim=1)


class DeepLOB(nn.Module):
    """The network. Input `(batch, 1, 100, 40)`, output `(batch, 3)`."""

    def __init__(
        self,
        snapshots: int = SNAPSHOTS,
        features: int = FEATURES,
        classes: int = CLASSES,
        hidden: int = 64,
        branch_channels: int = 64,
        channels: int = 32,
    ) -> None:
        super().__init__()
        self.snapshots = snapshots
        self.features = features

        # 40 numbers -> 20 (price with its volume) -> 10 (ask with bid) -> 1 (all levels)
        self.block1 = _conv_block(1, channels, (1, 2), stride=(1, 2))
        self.block2 = _conv_block(channels, channels, (1, 2), stride=(1, 2))
        self.block3 = _conv_block(channels, channels, (1, features // 4))

        self.inception = Inception(channels, branch_channels)
        self.lstm = nn.LSTM(branch_channels * 3, hidden, batch_first=True)
        self.out = nn.Linear(hidden, classes)

    def forward(self, x: Tensor) -> Tensor:
        self.check_input(x)

        x = self.block3(self.block2(self.block1(x)))
        x = self.inception(x)

        # (batch, channels, time, 1) -> (batch, time, channels) for the LSTM
        sequence = x.squeeze(-1).permute(0, 2, 1)
        _, (last_hidden, _) = self.lstm(sequence)
        scores: Tensor = self.out(last_hidden[-1])
        return scores

    def check_input(self, x: Tensor) -> None:
        """Explain a wrong shape, instead of failing three layers deep."""
        if x.dim() != 4:
            raise DeepLOBError(
                f"expected 4 dimensions (batch, 1, {self.snapshots}, {self.features}), "
                f"got {tuple(x.shape)}"
            )
        _, channels, snapshots, features = x.shape
        if (channels, snapshots, features) != (1, self.snapshots, self.features):
            raise DeepLOBError(
                f"expected each example to be (1, {self.snapshots}, {self.features}), "
                f"got {(channels, snapshots, features)}"
            )


def count_parameters(model: nn.Module) -> int:
    """How many numbers the model learns."""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
