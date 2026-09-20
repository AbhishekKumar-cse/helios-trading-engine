"""Tests for the FI-2010 loader and day split (steps 037-038, 049).

Most tests build a tiny fake FI-2010 zip, so they run everywhere (including CI).
Tests on the real dataset are skipped when it is not on disk (for example on CI).
The one that reads the whole 607 MB training file is marked `slow` and is left out of the
default run; run it with `uv run pytest -m slow`.
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
    concat,
    list_files,
    load,
    load_split,
    read_matrix,
    split_matrix,
    take,
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


# ---------------------------------------------------------------- day split (step 049)


def split_zip(tmp_path: Path, train_events: int = 10, test_events: int = 4) -> Path:
    """A fake FI-2010 zip holding all four files."""
    zip_path = tmp_path / "fi2010.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, n in [(TRAIN_FILE, train_events)] + [(t, test_events) for t in TEST_FILES]:
            matrix = fake_matrix(n)
            zf.writestr(name, "\n".join(" ".join(f"{v:.7e}" for v in row) for row in matrix))
    return zip_path


def test_split_lengths(tmp_path: Path) -> None:
    split = load_split(split_zip(tmp_path, train_events=10, test_events=4))
    assert split.train.n_events == 8  # first 80 % of days 1-7
    assert split.val.n_events == 2  # last 20 %
    assert split.test.n_events == 12  # 3 test days x 4 events


def test_validation_comes_after_training(tmp_path: Path) -> None:
    """No shuffling: the val events must be the LAST ones of the training file."""
    zip_path = split_zip(tmp_path, train_events=10)
    whole = load(TRAIN_FILE, zip_path)
    split = load_split(zip_path)
    np.testing.assert_array_equal(split.train.labels, whole.labels[:8])
    np.testing.assert_array_equal(split.val.labels, whole.labels[8:])


def test_split_keeps_shapes(tmp_path: Path) -> None:
    split = load_split(split_zip(tmp_path))
    for part in (split.train, split.val, split.test):
        assert part.lob.shape == (part.n_events, 40)
        assert part.features.shape == (part.n_events, 104)
        assert part.labels.shape == (part.n_events, 5)


def test_val_fraction_can_be_changed(tmp_path: Path) -> None:
    split = load_split(split_zip(tmp_path, train_events=10), val_fraction=0.5)
    assert (split.train.n_events, split.val.n_events) == (5, 5)


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.2, 1.5])
def test_bad_val_fraction_is_rejected(tmp_path: Path, bad: float) -> None:
    with pytest.raises(FI2010Error, match="val_fraction"):
        load_split(split_zip(tmp_path), val_fraction=bad)


def test_concat_joins_in_order(tmp_path: Path) -> None:
    a = split_matrix(fake_matrix(3))
    b = split_matrix(fake_matrix(2))
    joined = concat([a, b])
    assert joined.n_events == 5
    np.testing.assert_array_equal(joined.labels[:3], a.labels)
    np.testing.assert_array_equal(joined.labels[3:], b.labels)


def test_concat_needs_parts() -> None:
    with pytest.raises(FI2010Error, match="nothing to join"):
        concat([])


def test_take_range_is_checked() -> None:
    data = split_matrix(fake_matrix(5))
    assert take(data, 1, 3).n_events == 2
    for start, stop in [(-1, 3), (3, 3), (0, 6), (4, 2)]:
        with pytest.raises(FI2010Error, match="bad range"):
            take(data, start, stop)


@pytest.mark.slow
@pytest.mark.skipif(not DEFAULT_ZIP.is_file(), reason="FI-2010 dataset not downloaded")
def test_real_split_lengths() -> None:
    """The real thing: 254,750 events in days 1-7 and 139,587 in days 8-10."""
    split = load_split()
    assert split.train.n_events == 203800
    assert split.val.n_events == 50950
    assert split.train.n_events + split.val.n_events == 254750
    assert split.test.n_events == 55478 + 52172 + 31937 == 139587
    assert split.test.lob.shape == (139587, 40)
