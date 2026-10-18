"""Replay one seeded-random retained equity result using its archived Python source.

No model fit, new experiment, alpha result or TEST access is performed. Transient
UUIDs may differ; observed returns, prices, quantities, fees and ledger values must
match exactly. Source archives and original results are never modified.
"""

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", type=int, default=169)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    root = args.round.resolve()
    if not root.is_relative_to(repo / "reports_out/equity_research"):
        raise ValueError("replay requires a retained local equity round")
    protocol = json.loads((root / "protocol.json").read_text())
    summary = json.loads((root / "summary.json").read_text())
    assert digest(root / "protocol.json") == summary["protocol_sha256"]
    archive = root / "source"
    for relative, expected in protocol["source_hashes"].items():
        path = (archive / relative).resolve()
        assert path.is_relative_to(archive) and digest(path) == expected
    assert not any(name == "helios" or name.startswith("helios.") for name in sys.modules)
    sys.path.insert(0, str(archive / "research"))
    import numpy as np
    from sqlalchemy import create_engine, text

    import helios.backtest.engine as archived_engine
    from helios.alpha.output import evaluate_definition
    from helios.backtest.equity import eligible_sessions, replay_session
    from helios.common.db import DatabaseSettings
    from helios.equities.config import EquityResearchPolicy
    from helios.equities.inputs import load_equity_inputs
    from helios.registry.results import get_result
    from helios.sim.evaluate import _definition

    assert Path(archived_engine.__file__).resolve().is_relative_to(archive)
    eligible = []
    for entry in summary["results"]:
        evidence = json.loads(Path(entry["artifact"]).read_text())
        if entry["status"] != "INVALID" and evidence["protocol"]["definition"]["expression"]:
            eligible.append(entry)
    selected = random.Random(args.seed).choice(eligible)
    evidence = json.loads(Path(selected["artifact"]).read_text())
    assert digest(Path(selected["artifact"])) == selected["artifact_sha256"]
    engine = create_engine(DatabaseSettings(_env_file=repo / ".env").url(), pool_pre_ping=True)
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        stored = get_result(connection, selected["run_id"])
        assert stored.evaluation_json["artifact_sha256"] == selected["artifact_sha256"]
        definition = _definition(connection, selected["alpha_id"], 1)
        before = connection.execute(text("SELECT count(*) FROM test_set_access")).scalar_one()
    policy = EquityResearchPolicy.model_validate(evidence["protocol"]["policy"])
    source = load_equity_inputs(Path(protocol["source_snapshot"]), selected["symbol"], policy)
    alpha = evaluate_definition(definition, source.features, interval=policy.interval)
    sessions, excluded = eligible_sessions(source)
    assert excluded == evidence["coverage"]["excluded"]
    daily, stress, fills, snapshots = [], [], [], []
    for frame in sessions:
        base = replay_session(
            frame,
            alpha,
            policy,
            snapshot_id=summary["snapshot_id"],
            alpha_id=selected["alpha_id"],
            code_commit=stored.code_commit,
        )
        doubled = replay_session(
            frame,
            alpha,
            policy,
            snapshot_id=summary["snapshot_id"],
            alpha_id=selected["alpha_id"],
            code_commit=stored.code_commit,
            multiplier=2,
        )
        daily.append(base.net_return)
        stress.append(doubled.net_return)
        fills.extend(base.fills)
        snapshots.extend(base.snapshots)
    np.testing.assert_array_equal(daily, [row["net_return"] for row in evidence["series"]])
    np.testing.assert_array_equal(stress, evidence["stress_session_returns"])
    numeric_keys = ("symbol", "side", "quantity", "price", "fee", "fee_asset", "timestamp", "mode")
    assert [{key: fill[key] for key in numeric_keys} for fill in fills] == [
        {key: fill[key] for key in numeric_keys} for fill in evidence["fills"]
    ]
    assert snapshots == evidence["ledger_snapshots"]
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        after = connection.execute(text("SELECT count(*) FROM test_set_access")).scalar_one()
    assert before == after == 0
    result = dict(
        version="nse_archived_replay_v1",
        random_seed=args.seed,
        eligible_results=len(eligible),
        selected_run_id=selected["run_id"],
        symbol=selected["symbol"],
        alpha_id=selected["alpha_id"],
        original_code_commit=stored.code_commit,
        original_dirty=stored.dirty,
        archived_engine_sha256=digest(Path(archived_engine.__file__)),
        source_archive_verified=True,
        original_artifact_sha256=selected["artifact_sha256"],
        sessions=len(sessions),
        fills=len(fills),
        ledger_snapshots=len(snapshots),
        daily_returns_exact=True,
        stress_returns_exact=True,
        fill_numeric_fields_exact=True,
        ledger_snapshots_exact=True,
        identity_fields_excluded=["fill_id", "order_id", "venue_id"],
        registry_read_only=True,
        model_refit=False,
        test_accesses=after,
        original_artifact_unchanged=digest(Path(selected["artifact"]))
        == selected["artifact_sha256"],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
