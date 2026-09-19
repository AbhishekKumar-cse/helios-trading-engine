"""FI-2010 limit-order-book benchmark loader (steps 037-038).

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
