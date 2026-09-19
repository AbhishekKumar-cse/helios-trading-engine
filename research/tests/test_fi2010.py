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
    LABEL_HORIZONS,
    LABEL_VALUES,
    TEST_FILES,
    TRAIN_FILE,
    FI2010Error,
    list_files,
    load,
    read_matrix,
    split_matrix,
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


# ---------------------------------------------------------------- step 038: split


def fake_matrix(n: int) -> np.ndarray:
    """149 x n matrix: row r holds the value r (so we can see which rows went where),
    except the 5 label rows, which cycle through 1, 2, 3."""
    m = np.repeat(np.arange(FI2010_ROWS, dtype=np.float64)[:, None], n, axis=1)
    m[-5:] = (np.arange(5 * n).reshape(5, n) % 3) + 1
    return m


def test_split_shapes_and_orientation() -> None:
    data = split_matrix(fake_matrix(7))
    assert data.n_events == 7
    assert data.lob.shape == (7, 40)
    assert data.features.shape == (7, 104)
    assert data.labels.shape == (7, 5)
    # rows 0-39 -> lob columns, rows 40-143 -> feature columns
    np.testing.assert_array_equal(data.lob[0], np.arange(40))
    np.testing.assert_array_equal(data.features[0], np.arange(40, 144))
    assert data.labels.dtype == np.int8


def test_labels_for_each_horizon() -> None:
    m = fake_matrix(4)
    data = split_matrix(m)
    for i, k in enumerate(LABEL_HORIZONS):
        np.testing.assert_array_equal(data.labels_for(k), m[144 + i].astype(np.int8))
    with pytest.raises(FI2010Error, match="horizon must be one of"):
        data.labels_for(15)


def test_bad_label_value_is_rejected() -> None:
    m = fake_matrix(3)
    m[-1, 0] = 4.0
    with pytest.raises(FI2010Error, match="labels must be 1, 2 or 3"):
        split_matrix(m)


def test_wrong_shape_is_rejected() -> None:
    with pytest.raises(FI2010Error, match="149 rows"):
        split_matrix(np.ones((40, 3)))


def test_load_reads_and_splits(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path, TRAIN_FILE, fake_matrix(3))
    data = load(TRAIN_FILE, zip_path)
    assert data.lob.shape == (3, 40)


@pytest.mark.skipif(not DEFAULT_ZIP.is_file(), reason="FI-2010 dataset not downloaded")
def test_real_day10_split() -> None:
    data = load("Test_Dst_NoAuction_DecPre_CF_9.txt")
    assert (data.lob.shape, data.features.shape, data.labels.shape) == (
        (31937, 40),
        (31937, 104),
        (31937, 5),
    )
    assert set(np.unique(data.labels).tolist()) <= set(LABEL_VALUES)
    # level-1 ask price must not be below level-1 bid price (normalised, but order kept)
    assert (data.lob[:, 0] >= data.lob[:, 2]).mean() > 0.99
