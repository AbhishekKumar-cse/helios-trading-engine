"""Shared read-only summaries of retained registry and sandbox evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st
from sqlalchemy import Engine, create_engine

from helios.common.db import get_settings
from helios.common.lineage import PROJECT_ROOT
from helios.dashboard.dataset_inventory import DatasetInventory, collect_inventory
from helios.dashboard.registry import read_registry
from helios.data.equities import sha256


@st.cache_resource
def _registry_engine() -> Engine:
    return create_engine(
        get_settings().url(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 4, "options": "-c statement_timeout=10000"},
    )


@st.cache_data(ttl=60, show_spinner=False)
def registry_snapshot() -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    try:
        definitions, attempts = read_registry(_registry_engine())
        return definitions, attempts, True
    except Exception:
        return [], [], False


@st.cache_data(ttl=120, show_spinner=False)
def inventory_snapshot() -> tuple[list[DatasetInventory], list[str]]:
    return collect_inventory(PROJECT_ROOT)


def read_account(path: Path, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    path = path.resolve()
    if not any(
        path.is_relative_to((root / directory).resolve())
        for directory in ("reports_out/nse_sandbox", "reports_out/research_lab/runs")
    ):
        raise ValueError("unknown sandbox account path")
    hashes = json.loads((path / "artifact_hashes.json").read_text())
    for name in ("protocol.json", "result.json"):
        if sha256(path / name) != hashes[name]:
            raise ValueError("retained account evidence changed")
    protocol = json.loads((path / "protocol.json").read_text())
    result = json.loads((path / "result.json").read_text())
    if (
        result["protocol_sha256"] != hashes["protocol.json"]
        or result["eligible"]
        or result["test_accesses"]
        or protocol["test_accesses"]
        or protocol["purpose"] != "interactive_nse_development_not_alpha_validation"
    ):
        raise ValueError("sandbox identity/lineage mismatch")
    return dict(path=path, protocol=protocol, result=result)


def retained_accounts(root: Path = PROJECT_ROOT) -> tuple[list[dict[str, Any]], list[str]]:
    accounts, issues = [], []
    paths = [
        *(root / "reports_out/nse_sandbox").glob("*/result.json"),
        *(root / "reports_out/research_lab/runs").glob("*/*/result.json"),
    ]
    for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            accounts.append(read_account(path.parent, root))
        except (OSError, ValueError, KeyError, TypeError):
            issues.append(f"{path.parent.name}: retained account integrity could not be verified")
    return accounts, issues
