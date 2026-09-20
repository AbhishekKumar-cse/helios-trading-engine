"""INSERT statements shared by the registry tests (steps 061-062).

Kept in one place so the schema tests and the insert-only tests describe the same rows. Not
a test module itself: pytest only collects files named test_*.py.
"""

COMMIT = "a" * 40  # a git commit is 40 characters
HASH = "b" * 64  # a sha256 fingerprint is 64

DEFINITION = """
INSERT INTO alpha_definitions
    (alpha_id, version, name, provenance, spec_json, feature_set_version,
     horizon_family, horizon_periods, author, code_commit)
VALUES (:alpha_id, :version, 'test alpha', :provenance, '{"rule": "momentum"}'::jsonb, 'fs_v1',
        :family, :horizon, 'abhishek', :commit)
"""

GATE_CONFIG = """
INSERT INTO alpha_gate_config
    (config_id, sharpe_min, fitness_min, fitness_turnover_floor, turnover_min, turnover_max,
     stability_min_positive_fraction, cost_stress_multiplier, cost_stress_sharpe_min,
     config_hash, author, effective_from)
VALUES (:config_id, 1.0, 1.0, 0.125, :turnover_min, :turnover_max, 0.5, :stress, 0.0,
        :hash, 'abhishek', now())
"""

SNAPSHOT = """
INSERT INTO data_snapshots
    (snapshot_id, source, interval, symbols, first_open_time, last_open_time,
     file_count, row_count, total_bytes, code_commit)
VALUES (:id, 'test', '1h', '["TESTAUSDT"]'::jsonb, 1, 2, 1, 10, 100, :commit)
"""

EXPERIMENT = """
INSERT INTO experiments (kind, hypothesis, params, author, status)
VALUES ('alpha', 'a hypothesis written before the run', '{}'::jsonb, 'abhishek', 'planned')
RETURNING experiment_id
"""

RESULT = """
INSERT INTO alpha_results
    (run_id, experiment_id, alpha_id, version, split, snapshot_id, gate_config_id,
     sharpe, annual_return, turnover, fitness, max_drawdown, hit_rate,
     periods, gate_results, status, code_commit, config_hash, seed, dirty)
VALUES (:run_id, :experiment_id, :alpha_id, :version, :split, :snapshot_id, :config_id,
        :sharpe, 0.25, :turnover, 1.4, :drawdown, :hit_rate,
        :periods, '{"G1": true}'::jsonb, :status, :commit, :hash, 0, false)
"""

ACCESS = """
INSERT INTO test_set_access (alpha_id, version, snapshot_id, actor, purpose)
VALUES (:alpha_id, :version, :snapshot_id, 'abhishek', :purpose)
"""
