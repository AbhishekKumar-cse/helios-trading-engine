"""FI-2010 limit-order-book benchmark loader (steps 037-039, 049).

FI-2010 (Ntakaris et al., 2018) holds 10 days of order-book events for 5 Nasdaq Nordic
stocks. We use the DeepLOB packaging: one zip with 4 text files (decimal-precision
normalised, auction periods removed):

    Train_Dst_NoAuction_DecPre_CF_7.txt   days 1-7
    Test_Dst_NoAuction_DecPre_CF_7.txt    day 8
    Test_Dst_NoAuction_DecPre_CF_8.txt    day 9
    Test_Dst_NoAuction_DecPre_CF_9.txt    day 10

Each file is a matrix with **149 rows** and **one column per event**. Rows 0-39 are the
10-level order book, 40-143 hand-made features, and the last 5 rows are labels.

The files are read directly from the zip, so the ~940 MB of text is never extracted into the
(OneDrive-synced) project folder.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

# research/helios/ml/fi2010.py -> parents[3] is the project root
DEFAULT_ZIP = Path(__file__).resolve().parents[3] / "data" / "fi2010" / "FI2010_DeepLOB_data.zip"
FI2010_ROWS = 149

TRAIN_FILE = "Train_Dst_NoAuction_DecPre_CF_7.txt"
TEST_FILES = (
    "Test_Dst_NoAuction_DecPre_CF_7.txt",
    "Test_Dst_NoAuction_DecPre_CF_8.txt",
    "Test_Dst_NoAuction_DecPre_CF_9.txt",
)

Matrix = npt.NDArray[np.float64]


class FI2010Error(Exception):
    """Raised when the FI-2010 zip or one of its files is missing or malformed."""


def list_files(zip_path: Path = DEFAULT_ZIP) -> list[str]:
    """Names of the files inside the FI-2010 zip."""
    if not zip_path.is_file():
        raise FI2010Error(f"FI-2010 zip not found: {zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        return zf.namelist()


def read_matrix(member: str, zip_path: Path = DEFAULT_ZIP) -> Matrix:
    """Read one FI-2010 file from the zip as a float64 matrix of shape (149, n_events)."""
    if member not in list_files(zip_path):
        raise FI2010Error(f"{member} is not inside {zip_path}")

    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="ascii")
        try:
            matrix = np.loadtxt(text, dtype=np.float64, ndmin=2)
        except ValueError as exc:
            raise FI2010Error(f"{member}: could not parse numbers ({exc})") from exc

    if matrix.shape[0] != FI2010_ROWS:
        raise FI2010Error(f"{member}: expected {FI2010_ROWS} rows, found {matrix.shape[0]}")
    if matrix.shape[1] == 0:
        raise FI2010Error(f"{member}: contains no events")
    if not np.isfinite(matrix).all():
        raise FI2010Error(f"{member}: contains NaN or infinite values")
    return matrix


# ---------------------------------------------------------------- step 038: split the matrix

LOB_ROWS = slice(0, 40)  # 10 levels x (ask price, ask volume, bid price, bid volume)
FEATURE_ROWS = slice(40, 144)  # 104 hand-made features
LABEL_ROWS = slice(144, 149)  # 5 label rows
LABEL_HORIZONS = (10, 20, 30, 50, 100)  # events ahead, one per label row
LABEL_VALUES = (1, 2, 3)  # 1 = up, 2 = stationary, 3 = down

Labels = npt.NDArray[np.int8]


@dataclass(frozen=True)
class FI2010Data:
    """One FI-2010 file split into its parts, with one row per event (samples first).

    - lob:      (n_events, 40)  order book, level by level: ask price, ask volume,
                                bid price, bid volume (level 1 first)
    - features: (n_events, 104) hand-made features from the FI-2010 paper
    - labels:   (n_events, 5)   mid-price direction 10/20/30/50/100 events ahead,
                                1 = up, 2 = stationary, 3 = down
    """

    lob: Matrix
    features: Matrix
    labels: Labels

    @property
    def n_events(self) -> int:
        return int(self.lob.shape[0])

    def labels_for(self, horizon: int) -> Labels:
        """Label column for one horizon (10, 20, 30, 50 or 100 events ahead)."""
        if horizon not in LABEL_HORIZONS:
            raise FI2010Error(f"horizon must be one of {LABEL_HORIZONS}, got {horizon}")
        return self.labels[:, LABEL_HORIZONS.index(horizon)]


def split_matrix(matrix: Matrix) -> FI2010Data:
    """Split a (149, n_events) FI-2010 matrix into order book, features and labels."""
    if matrix.ndim != 2 or matrix.shape[0] != FI2010_ROWS:
        raise FI2010Error(f"expected a matrix with {FI2010_ROWS} rows, got shape {matrix.shape}")

    raw_labels = matrix[LABEL_ROWS]
    if not np.isin(raw_labels, LABEL_VALUES).all():
        bad = np.unique(raw_labels[~np.isin(raw_labels, LABEL_VALUES)])
        raise FI2010Error(f"labels must be 1, 2 or 3; found {bad[:5].tolist()}")

    return FI2010Data(
        lob=np.ascontiguousarray(matrix[LOB_ROWS].T),
        features=np.ascontiguousarray(matrix[FEATURE_ROWS].T),
        labels=np.ascontiguousarray(raw_labels.T).astype(np.int8),
    )


def load(member: str, zip_path: Path = DEFAULT_ZIP) -> FI2010Data:
    """Read one FI-2010 file and split it (`read_matrix` + `split_matrix`)."""
    return split_matrix(read_matrix(member, zip_path))


# ---------------------------------------------------------------- day split (step 049)

VAL_FRACTION = 0.2
"""Share of the training file (days 1-7) held back for validation, as in the DeepLOB paper."""


@dataclass(frozen=True)
class FI2010Split:
    """Train / validation / test parts, split exactly as the DeepLOB paper does.

    - train: first 80 % of the days 1-7 file
    - val:   last 20 % of the same file (kept in time order, never shuffled: the validation
             events must come *after* the training events, or the model sees its own future)
    - test:  days 8, 9 and 10, joined in order
    """

    train: FI2010Data
    val: FI2010Data
    test: FI2010Data


def concat(parts: Sequence[FI2010Data]) -> FI2010Data:
    """Join several FI-2010 parts end to end, keeping their order."""
    if not parts:
        raise FI2010Error("nothing to join")
    return FI2010Data(
        lob=np.concatenate([p.lob for p in parts]),
        features=np.concatenate([p.features for p in parts]),
        labels=np.concatenate([p.labels for p in parts]),
    )


def take(data: FI2010Data, start: int, stop: int) -> FI2010Data:
    """The events from `start` (included) to `stop` (excluded), in order."""
    if not 0 <= start < stop <= data.n_events:
        raise FI2010Error(f"bad range {start}:{stop} for {data.n_events} events")
    return FI2010Data(
        lob=data.lob[start:stop],
        features=data.features[start:stop],
        labels=data.labels[start:stop],
    )


def load_split(zip_path: Path = DEFAULT_ZIP, val_fraction: float = VAL_FRACTION) -> FI2010Split:
    """Load FI-2010 and split it by day: train/val from days 1-7, test from days 8-10.

    Returns plain numpy arrays: nothing here depends on PyTorch.
    """
    if not 0.0 < val_fraction < 1.0:
        raise FI2010Error(f"val_fraction must be between 0 and 1, got {val_fraction}")

    days_1_to_7 = load(TRAIN_FILE, zip_path)
    cut = int(days_1_to_7.n_events * (1.0 - val_fraction))
    if cut in (0, days_1_to_7.n_events):
        raise FI2010Error("training file is too small to split")

    return FI2010Split(
        train=take(days_1_to_7, 0, cut),
        val=take(days_1_to_7, cut, days_1_to_7.n_events),
        test=concat([load(name, zip_path) for name in TEST_FILES]),
    )
