"""Intraday minute features with causal availability and next-minute labels."""

import numpy as np
import pandas as pd

from helios.ml.equity_pilot import features_for


def minute_samples(bars: pd.DataFrame, *, include_unlabelled: bool = False) -> pd.DataFrame:
    if bars.empty or bars.symbol.nunique() != 1:
        raise ValueError("minute features require one nonempty instrument")
    frame = bars.sort_values("timestamp").reset_index(drop=True).copy()
    if frame.timestamp.duplicated().any():
        raise ValueError("duplicate minute timestamp")
    gap = frame.timestamp.diff() != pd.Timedelta(minutes=1)
    same = frame.session_date == frame.session_date.shift()
    good = (frame.volume > 0) & frame.full_bar
    broken = gap | ~same | ~good | ~good.shift(fill_value=False)
    segment = broken.cumsum()
    close = frame.close.groupby(segment)
    for lag in (1, 2, 3):
        frame[f"return_{lag}"] = frame.close / close.shift(lag) - 1
    frame["volatility_3"] = frame.return_1.groupby(segment).transform(
        lambda values: values.rolling(3, min_periods=3).std(ddof=0)
    )
    frame["body"] = frame.close / frame.open - 1
    frame["range"] = (frame.high - frame.low) / frame.open
    frame["close_location"] = (frame.close - frame.low) / (frame.high - frame.low).replace(
        0, np.nan
    )
    frame["relative_volume_3"] = frame.volume / frame.volume.groupby(segment).transform(
        lambda values: values.rolling(3, min_periods=3).mean()
    )
    frame["open_gap"] = frame.open / close.shift(1) - 1
    local = frame.timestamp.dt.tz_convert("Asia/Kolkata")
    frame["bar_slot"] = local.dt.hour * 60 + local.dt.minute - 555
    frame["feature_available"] = good & np.isfinite(
        frame[list(features_for("60m"))].to_numpy(dtype=float)
    ).all(axis=1)
    frame["label_open_time"] = frame.timestamp.shift(-1)
    frame["label_end_time"] = frame.available_at.shift(-1)
    frame["label_session"] = frame.session_date.shift(-1)
    frame["target"] = (frame.close / frame.open - 1).shift(-1)
    if include_unlabelled:
        return frame
    available: pd.Series[bool] = pd.Series(
        frame.feature_available
        & good.shift(-1, fill_value=False)
        & (frame.label_open_time - frame.timestamp == pd.Timedelta(minutes=1))
        & (frame.session_date == frame.label_session)
        & (frame.available_at <= frame.label_open_time)
        & np.isfinite(frame.target),
        index=frame.index,
        dtype=bool,
    )
    return frame.loc[available].reset_index(drop=True)
