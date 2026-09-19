"""Tests for the FI-2010 loader (step 037).

Most tests build a tiny fake FI-2010 zip, so they run everywhere (including CI).
One test reads the real day-10 test file when the dataset is on disk, and is skipped otherwise.
"""

import zipfile
from pathlib import Path

import numpy as np
import pytest

from helios.ml.fi2010 import (
    DEFAULT_ZIP,
    FI2010_ROWS,
    TEST_FILES,
    TRAIN_FILE,
    FI2010Error,
    list_files,
    read_matrix,
)


def make_zip(tmp_path: Path, name: str, matrix: np.ndarray) -> Path:
    """Write `matrix` in the FI-2010 text format (space separated, one row per line)."""
    lines = [" ".join(f"{v:.7e}" for v in row) for row in matrix]
    zip_path = tmp_path / "fi2010.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(name, "\n".join(lines) + "\n")
    return zip_path


def test_reads_matrix_with_149_rows(tmp_path: Path) -> None:
    fake = np.arange(FI2010_ROWS * 4, dtype=np.float64).reshape(FI2010_ROWS, 4) / 100
    zip_path = make_zip(tmp_path, TRAIN_FILE, fake)
    m = read_matrix(TRAIN_FILE, zip_path)
    assert m.shape == (FI2010_ROWS, 4)
    assert m.dtype == np.float64
    np.testing.assert_allclose(m, fake, rtol=1e-7)


def test_single_event_still_2d(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path, TRAIN_FILE, np.ones((FI2010_ROWS, 1)))
    assert read_matrix(TRAIN_FILE, zip_path).shape == (FI2010_ROWS, 1)


def test_wrong_row_count_is_rejected(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path, TRAIN_FILE, np.ones((148, 3)))
    with pytest.raises(FI2010Error, match="expected 149 rows"):
        read_matrix(TRAIN_FILE, zip_path)


def test_nan_is_rejected(tmp_path: Path) -> None:
    fake = np.ones((FI2010_ROWS, 3))
    fake[5, 1] = np.nan
    zip_path = make_zip(tmp_path, TRAIN_FILE, fake)
    with pytest.raises(FI2010Error, match="NaN"):
        read_matrix(TRAIN_FILE, zip_path)


def test_missing_member_is_rejected(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path, TRAIN_FILE, np.ones((FI2010_ROWS, 2)))
    with pytest.raises(FI2010Error, match="is not inside"):
        read_matrix(TEST_FILES[0], zip_path)


def test_missing_zip_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FI2010Error, match="not found"):
        list_files(tmp_path / "nope.zip")


@pytest.mark.skipif(not DEFAULT_ZIP.is_file(), reason="FI-2010 dataset not downloaded")
def test_real_day10_file() -> None:
    assert sorted(list_files()) == sorted([TRAIN_FILE, *TEST_FILES])
    m = read_matrix("Test_Dst_NoAuction_DecPre_CF_9.txt")
    assert m.shape == (FI2010_ROWS, 31937)
    labels = m[-5:]
    assert set(np.unique(labels)) <= {1.0, 2.0, 3.0}
