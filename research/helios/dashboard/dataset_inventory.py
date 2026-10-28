"""Retained data inventory from manifests and Parquet footers, never observation scans."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]


@dataclass(frozen=True)
class DatasetInventory:
    dataset_id: str
    name: str
    market: str
    family: str
    frequency: str
    provider: str
    status: str
    access: str
    rows: int | None
    symbols: tuple[str, ...]
    period: str
    fields: tuple[dict[str, str], ...]
    files: tuple[dict[str, Any], ...]
    evidence: str
    evidence_sha256: str


def field_info(name: str, dtype: str, market: str, *, derived: bool = False) -> dict[str, str]:
    category, unit, meaning, availability = (
        "Metadata",
        "See source contract",
        name.replace("_", " "),
        "Retained source metadata",
    )
    if name in {"open", "high", "low", "close", "adjusted_close", "source_close"}:
        category, unit = (
            "Price",
            "INR · historical units uncertified" if market == "NSE" else "USDT",
        )
        meaning = {
            "open": "First traded price in the bar",
            "high": "Highest price in the bar",
            "low": "Lowest price in the bar",
            "close": "Last traded price in the bar",
            "adjusted_close": "Vendor-adjusted close; corporate-action convention requires review",
            "source_close": "Original vendor close retained for scale screening",
        }[name]
        availability = "Completed bar; enforce available_at / source clock before use"
    elif name in {
        "volume",
        "source_volume",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
    }:
        category = "Volume & flow"
        unit = (
            "Count"
            if name == "trades"
            else "USDT"
            if name in {"quote_volume", "taker_buy_quote"}
            else "Vendor volume · units uncertified"
            if market == "NSE"
            else "Base asset"
        )
        meaning = {
            "volume": "Traded base volume in the bar",
            "quote_volume": "Traded quote-asset notional",
            "trades": "Number of trades in the bar",
            "taker_buy_base": "Aggressive-buy volume in base asset",
            "taker_buy_quote": "Aggressive-buy notional in quote asset",
            "source_volume": "Original vendor volume retained for screening",
        }[name]
        availability = "Completed bar"
    elif name.startswith("available__") or name in {
        "research_eligible",
        "screen_status",
        "full_bar",
        "session_slots",
        "session_open_minute",
    }:
        category, unit, meaning = (
            "Quality & availability",
            "Flag / source metadata",
            "Explicit availability, session completeness or screening state; "
            "never a guarantee of certification",
        )
    elif name in {
        "timestamp",
        "open_time",
        "close_time",
        "available_at",
        "session_date",
        "day",
        "period_start",
        "period_end",
    }:
        category, unit = "Time & availability", "UTC / date; see stored type"
        meaning = (
            "Information availability clock"
            if name == "available_at"
            else "Bar/session or filing-period clock; distinct from information availability"
        )
    elif name in {
        "symbol",
        "isin",
        "official_symbol",
        "official_isin",
        "identity_basis",
        "source_sha256",
        "sequence",
    }:
        category, unit = "Identity & lineage", "Identifier / hash"
    elif name in {"profit_inr", "profit_yoy_growth"}:
        category, unit = "Fundamental", "INR" if name == "profit_inr" else "Ratio"
        meaning = (
            "Retained consolidated quarterly profit"
            if name == "profit_inr"
            else "Derived year-over-year consolidated profit growth; "
            "symbol columns form its matrix axis"
        )
        availability = (
            "Filing available_at, carry-age and peer masks required; "
            "historical publication vintage uncertified"
        )
    elif derived:
        category, unit = "Derived feature", "See feature manifest"
        availability = "Completed input bars plus explicit available__ flag and warmup"
    return dict(
        Field=name,
        Meaning=meaning,
        Category=category,
        Type=dtype,
        Unit=unit,
        Availability=availability,
    )


def _json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("object manifest required")
    return data


def _parquet_dataset(
    root: Path,
    dataset_id: str,
    name: str,
    market: str,
    family: str,
    frequency: str,
    provider: str,
    status: str,
    paths: list[Path],
    evidence: Path,
    *,
    entries: list[dict[str, Any]] | None = None,
    matrix: bool = False,
) -> DatasetInventory:
    schema: dict[str, str] = {}
    files = []
    symbols: set[str] = set()
    dates: list[str] = []
    lookup = {str(e.get("path")): e for e in entries or []}
    for path in sorted(paths):
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("data outside project")
        parquet = pq.ParquetFile(path)
        arrow = parquet.schema_arrow
        for field in arrow:
            schema[field.name] = str(field.type)
        try:
            key = path.relative_to(evidence.parent).as_posix()
        except ValueError:
            key = ""
        entry = lookup.get(key, {})
        symbol = entry.get("symbol") or next(
            (p[7:] for p in path.parts if p.startswith("symbol=")), ""
        )
        if symbol:
            symbols.add(symbol)
        first, last = entry.get("first_session", ""), entry.get("last_session", "")
        if not first or not last:
            clock = next(
                (k for k in ("session_date", "day", "timestamp", "open_time") if k in arrow.names),
                None,
            )
            bounds = []
            if clock:
                index = arrow.names.index(clock)
                # Flat schemas only; footer statistics do not read observation pages.
                for group in range(parquet.metadata.num_row_groups):
                    stats = parquet.metadata.row_group(group).column(index).statistics
                    if stats is not None and stats.has_min_max:
                        for value in (stats.min, stats.max):
                            if clock == "open_time" and isinstance(value, int):
                                value = datetime.fromtimestamp(value / 1_000_000, tz=UTC)
                            bounds.append(str(value))
            if bounds:
                first, last = min(bounds), max(bounds)
        dates.extend(str(d) for d in (first, last) if d)
        files.append(
            dict(
                Path=path.relative_to(root).as_posix(),
                Symbol=symbol,
                Rows=parquet.metadata.num_rows,
                First=first,
                Last=last,
                Manifest_SHA256=entry.get("sha256", ""),
            )
        )
    if matrix:
        symbols.update(k for k in schema if k != "session_date")
        schema = {
            "profit_yoy_growth": "float64 matrix · symbols × session",
            "session_date": schema.get("session_date", "date"),
        }
    fields = [
        field_info(k, v, market, derived=family in {"Features", "Fundamental matrix"})
        for k, v in schema.items()
    ]
    # Feature units/descriptions are declared in the retained feature manifest.
    if family == "Features":
        descriptions = {}
        for manifest in sorted(evidence.glob("symbol=*/manifest.json")):
            for item in (_json(manifest).get("config") or {}).get("features", []):
                descriptions[item["name"]] = item
        for field in fields:
            if field["Field"] in descriptions:
                item = descriptions[field["Field"]]
                field.update(
                    Meaning=item["description"],
                    Unit=item["units"],
                    Availability=f"Warmup {item['warmup']} bars · lookback {item['lookback']} "
                    "· explicit availability flag",
                )
    raw = (
        evidence.read_bytes()
        if evidence.is_file()
        else "\n".join(f["Path"] for f in files).encode()
    )
    return DatasetInventory(
        dataset_id,
        name,
        market,
        family,
        frequency,
        provider,
        status,
        "Metadata only in this page; TRAIN/VALID access follows each frozen protocol; "
        "TEST remains sealed",
        sum(f["Rows"] for f in files),
        tuple(sorted(symbols)),
        f"{min(dates)} → {max(dates)}"
        if dates
        else "Not declared in per-file manifest; inspect source protocol",
        tuple(fields),
        tuple(files),
        evidence.relative_to(root).as_posix(),
        hashlib.sha256(raw).hexdigest(),
    )


def collect_inventory(root: Path) -> tuple[list[DatasetInventory], list[str]]:
    """Explicit supported collections: do not mistake execution-output tables for datasets."""
    root = root.resolve()
    datasets: list[DatasetInventory] = []
    issues: list[str] = []
    for manifest in sorted((root / "data/equities").glob("*/*/manifest.json")):
        try:
            data = _json(manifest)
            entries = [
                e for e in data.get("files", []) if str(e.get("path", "")).endswith(".parquet")
            ]
            groups: dict[str, list[dict[str, Any]]] = {}
            for entry in entries:
                frequency = entry.get("interval") or data.get("interval") or "1m"
                frequency = "1h" if frequency == "60m" else frequency
                groups.setdefault(frequency, []).append(entry)
            for frequency, group in groups.items():
                paths = [manifest.parent / e["path"] for e in group]
                datasets.append(
                    _parquet_dataset(
                        root,
                        manifest.parent.relative_to(root).as_posix() + ":" + frequency,
                        f"{manifest.parent.parent.name} / {manifest.parent.name} · {frequency}",
                        "NSE",
                        "Prices & volume",
                        frequency,
                        str(
                            data.get("provider")
                            or data.get("source")
                            or "Public NSE archive · see protocol"
                        ),
                        "Conditional scale-screened · G7 not certified"
                        if data.get("version") == "nse_public_minutes_v2"
                        else "Retained · historical units/corporate actions uncertified",
                        paths,
                        manifest,
                        entries=group,
                    )
                )
        except (OSError, ValueError, KeyError, TypeError):
            issues.append(f"{manifest.relative_to(root)}: metadata unavailable; collection omitted")
    for interval in ("1h", "1m"):
        for kind, pattern, family in (
            ("bars", f"data/processed/bars/source=binance/interval={interval}", "Prices & volume"),
            ("features", f"data/processed/features/feature_set=v1/interval={interval}", "Features"),
        ):
            base = root / pattern
            paths = sorted(base.glob(f"symbol=*/year=*/{kind}.parquet"))
            if paths:
                try:
                    # Directory identifies collection; inspect each file's schema independently.
                    datasets.append(
                        _parquet_dataset(
                            root,
                            pattern,
                            f"Binance {kind} · {interval}",
                            "Crypto",
                            family,
                            interval,
                            "Binance public bars"
                            if kind == "bars"
                            else "HELIOS causal feature store v1",
                            "Retained · explicit gaps/availability; no blanket certification",
                            paths,
                            base,
                        )
                    )
                except (OSError, ValueError):
                    issues.append(f"{pattern}: metadata unavailable")
    studies = root / "reports_out/equity_research"
    for path in sorted(studies.glob("*/panel.parquet")):
        if path.parent.name != "nse_official_panel_drift1_repair1":
            continue  # retain accepted panel, not duplicate/failed repairs
        try:
            datasets.append(
                _parquet_dataset(
                    root,
                    path.relative_to(root).as_posix(),
                    "Official NSE daily accepted panel",
                    "NSE",
                    "Prices & volume",
                    "1d",
                    "NSE official retained archives",
                    "Accepted panel retained · source/units certification incomplete",
                    [path],
                    path.parent / "protocol.json",
                )
            )
        except (OSError, ValueError):
            issues.append("Official daily panel metadata unavailable")
    for path in sorted(studies.glob("nse_profit_growth_fields*/profit_growth_fields.parquet")):
        try:
            datasets.append(
                _parquet_dataset(
                    root,
                    path.relative_to(root).as_posix(),
                    f"Profit growth matrix / {path.parent.name}",
                    "NSE",
                    "Fundamental matrix",
                    "1d / filing carry",
                    "NSE filings → HELIOS derived matrix",
                    "Retained derived fields · publication vintage/units uncertified",
                    [path],
                    path.parent / "protocol.json",
                    matrix=True,
                )
            )
            facts = path.parent / "quarterly_profit_facts.json"
            values = json.loads(facts.read_text())
            keys = sorted({key for item in values for key in item})
            datasets.append(
                DatasetInventory(
                    facts.relative_to(root).as_posix(),
                    f"Quarterly profit facts / {path.parent.name}",
                    "NSE",
                    "Company filings",
                    "Filing event",
                    "NSE consolidated financial filings",
                    "Retained facts · historical receipt/publication vintage uncertified",
                    "Publication-clock and carry-age restrictions apply",
                    len(values),
                    tuple(sorted({v["symbol"] for v in values})),
                    " → ".join(
                        sorted({v["period_end"] for v in values})[
                            :: max(1, len({v["period_end"] for v in values}) - 1)
                        ]
                    ),
                    tuple(field_info(key, "JSON source field", "NSE") for key in keys),
                    (),
                    facts.relative_to(root).as_posix(),
                    hashlib.sha256(facts.read_bytes()).hexdigest(),
                )
            )
        except (OSError, ValueError, KeyError, TypeError):
            issues.append(f"{path.parent.name}: fundamental metadata unavailable")
    # Raw archives are listed as retained files, not promoted to queryable fields.
    for directory, name, market, family, pattern, frequency in (
        (
            "data/bybit/orderbook_spot",
            "Bybit spot order-book archive",
            "Crypto",
            "Order book",
            "*.zip",
            "Event",
        ),
        ("data/bybit/trades", "Bybit trade archive", "Crypto", "Trades", "*.gz", "Event"),
        (
            "reports_out/equity_research/nse_brain_field_probe_20261021",
            "NSE delivery schema sample",
            "NSE",
            "Delivery",
            "delivery_sample.raw",
            "Sample only",
        ),
    ):
        paths = sorted((root / directory).glob(pattern))
        if paths:
            datasets.append(
                DatasetInventory(
                    directory,
                    name,
                    market,
                    family,
                    frequency,
                    "Bybit public archive" if market == "Crypto" else "NSE public delivery sample",
                    "Raw archive retained · fields not validated"
                    if market == "Crypto"
                    else "Sample only · full history not collected",
                    "Requires a validated parser before research use",
                    None,
                    (),
                    "See retained archive name / source receipt",
                    (),
                    tuple(
                        dict(Path=p.relative_to(root).as_posix(), Bytes=p.stat().st_size)
                        for p in paths
                    ),
                    directory,
                    "",
                )
            )
    return datasets, issues
