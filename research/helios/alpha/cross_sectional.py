"""Same-timestamp transforms over an explicitly declared historical universe (091)."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from datetime import date
from typing import cast

import numpy as np
import pandas as pd

from helios.alpha.errors import DSLEvaluationError
from helios.alpha.evaluator import AlphaSeries, Mask, Values, _check_frame, _Evaluator, _masked
from helios.alpha.parser import parse_expression
from helios.alpha.safety import _parameters, _validate_tree
from helios.features.runner import FeatureFrame


class _CoinEvaluator(_Evaluator):
    def __init__(
        self,
        frame: FeatureFrame,
        params: dict[str, float],
        interval: str | None,
        panel: _UniverseEvaluator,
        listed: Mask,
    ) -> None:
        super().__init__(frame, params, interval)
        self.panel = panel
        self.listed = listed

    def visit(self, node: ast.expr) -> tuple[Values, Mask]:
        values, available = super().visit(node)
        return _masked(values, available & self.listed)

    def call(self, node: ast.Call) -> tuple[Values, Mask]:
        if cast(ast.Name, node.func).id in {"cs_rank", "cs_demean"}:
            return self.panel.cross(node)[self.frame.symbol]
        return super().call(node)


class _UniverseEvaluator:
    def __init__(
        self,
        frames: Mapping[str, FeatureFrame],
        bindings: Mapping[str, dict[str, float]],
        listing_dates: Mapping[str, date],
        interval: str | None,
    ) -> None:
        self.cutoffs = {
            symbol: (listing_dates[symbol] - date(1970, 1, 1)).days * 86_400_000_000
            for symbol in sorted(frames)
        }
        self.coins = {
            symbol: _CoinEvaluator(
                frame,
                bindings[symbol],
                interval,
                self,
                frame.open_time.to_numpy(dtype=np.int64) >= self.cutoffs[symbol],
            )
            for symbol in sorted(frames)
            for frame in (frames[symbol],)
        }
        self.cache: dict[int, dict[str, tuple[Values, Mask]]] = {}

    def cross(self, node: ast.Call) -> dict[str, tuple[Values, Mask]]:
        key = id(node)
        if key not in self.cache:
            inputs: dict[str, pd.Series] = {}
            for symbol, coin in self.coins.items():
                values, _ = coin.visit(node.args[0])
                inputs[symbol] = pd.Series(values, index=coin.frame.open_time.to_numpy())
            # Align only exact timestamps. Never join nearest rows, fill gaps or invent output rows.
            data = pd.concat(inputs, axis=1).sort_index()
            times = data.index.to_numpy(dtype=np.int64)
            eligible = times[:, None] >= np.array(list(self.cutoffs.values()))[None, :]
            counts = eligible.sum(axis=1)
            complete = (data.notna().to_numpy() & eligible).sum(axis=1) == counts
            complete &= counts > 0
            name = cast(ast.Name, node.func).id
            if name == "cs_rank":
                computed = data.rank(axis=1, method="average", pct=True)
            else:
                # Divide before summing to avoid overflow in the mean of large finite peers.
                matrix = data.to_numpy(dtype=np.float64)
                with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                    means = np.nansum(matrix / np.maximum(counts, 1)[:, None], axis=1)
                    computed = pd.DataFrame(
                        matrix - means[:, None], index=data.index, columns=data.columns
                    )
            computed.loc[~complete, :] = np.nan
            self.cache[key] = {}
            for symbol, coin in self.coins.items():
                values = computed[symbol].reindex(coin.frame.open_time.to_numpy()).to_numpy()
                self.cache[key][symbol] = _masked(values, np.isfinite(values))
        return self.cache[key]


def evaluate_universe_expression(
    source: str,
    features: Mapping[str, FeatureFrame],
    *,
    listing_dates: Mapping[str, date],
    params: Mapping[str, object] | None = None,
    interval: str | None = None,
) -> dict[str, AlphaSeries]:
    """Interpret one formula across the declared symbol mapping, returning existing rows.

    Supply first-available dates from helios.data.universe.listing_dates (or an
    explicit recorded catalog). Membership begins at inclusive UTC midnight.
    Before listing, all output is unavailable, including constants. At a cross
    call, every listed member must have a finite available operand at that exact
    timestamp; otherwise the whole cross-section is unavailable. Rank uses average
    ties divided by eligible count; demean subtracts the same-time universe mean.
    One eligible member ranks 1 and demeans to 0; these transforms are not IC metrics.
    No automatic final bounding, model execution or database write occurs.
    """
    tree = parse_expression(source)
    if not features:
        raise DSLEvaluationError("a non-empty declared universe is required")
    bindings: dict[str, dict[str, float]] = {}
    for symbol, frame in features.items():
        if not isinstance(symbol, str) or not symbol.strip() or frame.symbol != symbol:
            raise DSLEvaluationError("universe keys must be nonblank matching frame symbols")
        if symbol not in listing_dates or type(listing_dates[symbol]) is not date:
            raise DSLEvaluationError(f"a first-available date is required for {symbol!r}")
        _check_frame(frame, allow_empty=True)
        if (frame.open_time < np.iinfo(np.int64).min).any() or (
            frame.open_time > np.iinfo(np.int64).max
        ).any():
            raise DSLEvaluationError("timestamps must fit signed int64 UTC microseconds")
        names = tuple(frame.values.columns)
        bindings[symbol] = _parameters({} if params is None else params, names)
        _validate_tree(tree, names, bindings[symbol], interval, cross_sectional=True)
    panel = _UniverseEvaluator(features, bindings, listing_dates, interval)
    results: dict[str, AlphaSeries] = {}
    for symbol, coin in panel.coins.items():
        values, available = coin.visit(tree.body)
        results[symbol] = AlphaSeries(
            symbol,
            coin.frame.open_time.copy(),
            pd.Series(values, index=coin.frame.values.index.copy(), name="alpha", dtype="float64"),
            pd.Series(
                available, index=coin.frame.values.index.copy(), name="available", dtype=bool
            ),
        )
    return results
