# 5th Semester: Step-by-Step Work Order

This file turns [5thSem_Plan.md](5thSem_Plan.md) into **one numbered sequence of small steps** (each ≈ 2–6 hours).
Follow the numbers in order.

- **Plan ID** points to the task in the plan, which has more detail.
- **Owner:** **Q** Quant researcher · **S** Systems engineer · **M** ML engineer · **All** everyone.
- Steps in the same sprint with **different owners** can be done at the same time by different people. Steps with the **same owner** must be done in number order.
- Tick `[x]` when a step is done.

## Rules for every step (definition of done)

1. Work on a branch named after the plan ID, for example `5B-05-timestamps`.
2. Code has at least one test. `uv run pytest` passes locally.
3. Commit message starts with the plan ID: `5B-05: normalise ms/µs timestamps`.
4. Open a PR, get **1 teammate review**, CI is green, then merge.
5. No results are ever typed in by hand. Numbers come only from runs with lineage.

## Weekly routine

- **Monday (30 min):** pick this week's steps and write names next to them.
- **Friday (30 min):** each person shows what was merged. Tick boxes and move unfinished steps to next week.

---

## Sprint 1 (Week 1): Laptop setup (every member on their own laptop)

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 001 | Check free space: PowerShell → `Get-PSDrive C` | All | 5A-01 | You know the free GB |
| [ ] | 002 | Free space to **≥ 40 GB**: remove unused apps, run Storage Sense, move big personal files to another drive | All | 5A-01 | `Get-PSDrive C` shows ≥ 40 GB free |
| [ ] | 003 | Admin PowerShell: `wsl --install -d Ubuntu-24.04` → reboot → create Linux username/password | All | 5A-02 | Ubuntu terminal opens |
| [ ] | 004 | In Ubuntu: `sudo apt update && sudo apt upgrade -y && sudo apt install -y build-essential git curl unzip` | All | 5A-02 | `git --version` works |
| [ ] | 005 | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` → restart terminal → `uv python install 3.12` | All | 5A-02 | `uv --version` and `uv python list` show 3.12 |
| [ ] | 006 | Git identity: `git config --global user.name "…"` and `user.email "…"`; create SSH key `ssh-keygen -t ed25519`; add public key to GitHub | All | 5A-02 | `ssh -T git@github.com` greets you |
| [ ] | 007 | Install Docker Desktop → Settings → Resources → WSL integration → enable Ubuntu-24.04 | All | 5A-03 | `docker run hello-world` works **inside Ubuntu** |
| [ ] | 008 | Install VS Code + extensions: WSL, Python, Ruff, Docker. Open Ubuntu folder with `code .` | All | — | VS Code shows "WSL: Ubuntu" in the corner |
| [ ] | 009 | Team meeting: decide who is **Q**, **S**, **M** | All | 5A-11 | Names written down |

**Checkpoint 1:** all three laptops can run Ubuntu, uv, git and Docker.

---

## Sprint 2 (Week 2): Repository and project skeleton

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 010 | Create **private** GitHub repo `helios`; add teammates; protect `main` (require PR + 1 review + passing checks) | S | 5A-04 | Teammates accepted invites |
| [ ] | 011 | Clone into the **Linux home folder**: `cd ~ && git clone git@github.com:<org>/helios.git`. Do **not** put the repo in OneDrive: it is slow from WSL and sync breaks git | S | 5A-04 | `~/helios` exists |
| [ ] | 012 | Create the folder skeleton from `ARCHITECTURE_AND_TECH_STACK.md` §7: `docs/{decisions,spec,reports,research}`, `configs/`, `research/helios/`, `research/tests/`, `dashboards/streamlit/`, `infra/`, `scripts/`, `data/`, `.github/workflows/` (add `.gitkeep` files) | S | 5A-04 | `tree -L 2` matches the doc |
| [ ] | 013 | `.gitignore`: `data/`, `.env`, `.venv/`, `__pycache__/`, `*.parquet`, `*.zip`, `*.csv.gz`, `reports_out/` | S | 5A-04 | `git status` stays clean after copying data |
| [ ] | 014 | Copy documents: spec `.md` + Knowledge Base PDF → `docs/spec/`; SRS reports + PDF → `docs/reports/`; `ARCHITECTURE_AND_TECH_STACK.md` → repo root; `5thSem/ 6thSem/ 7thSem/` → repo root. Source is `/mnt/c/Users/bit/OneDrive/Desktop/helios/` | S | 5A-05 | Docs committed and pushed |
| [ ] | 015 | Copy downloaded data: `cp -r /mnt/c/Users/bit/OneDrive/Desktop/helios/data ~/helios/` | S | 5A-05 | `du -sh ~/helios/data` ≈ 339 MB; not in git |
| [ ] | 016 | Python project in repo root: `uv init --package --name helios`; set source dir to `research/helios`; add deps: `uv add numpy pandas pyarrow duckdb pydantic pyyaml` and dev deps `uv add --dev pytest hypothesis ruff mypy pre-commit` | S | 5A-06 | `uv sync` succeeds |
| [ ] | 017 | Add `research/helios/__init__.py` and `research/tests/test_smoke.py` (`assert 1 + 1 == 2`) | S | 5A-06 | `uv run pytest` → 1 passed |
| [ ] | 018 | Configure ruff (line length 100, import sorting) and mypy (strict for `helios/`) in `pyproject.toml` | S | 5A-06 | `uv run ruff check .` and `uv run mypy research/helios` clean |
| [ ] | 019 | `.pre-commit-config.yaml`: ruff, ruff-format, end-of-file-fixer, trailing-whitespace, **gitleaks**; `uv run pre-commit install` | S | 5A-07 | Committing a file with `AWS_SECRET_ACCESS_KEY=abc123…` is blocked |
| [ ] | 020 | `.github/workflows/ci.yml`: checkout → install uv → `uv sync` → ruff → mypy → pytest | S | 5A-08 | Green check on a PR |
| [ ] | 021 | `docs/TEAM.md`: names + roles, module owners, branch naming, commit format, PR rules, weekly routine | All | 5A-11 | Merged |
| [ ] | 022 | Every member clones the repo, runs `uv sync && uv run pytest` | All | — | Works on all 3 laptops |

**Checkpoint 2:** a PR from each member has been reviewed and merged with green CI.

---

## Sprint 3 (Week 3): Database, config, lineage + decisions

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 023 | `infra/docker-compose.yml`: `postgres:16` (volume, healthcheck) + `adminer`; `.env.example` with `POSTGRES_USER/PASSWORD/DB/PORT`; real `.env` is gitignored | S | 5A-09 | `docker compose up -d` → both containers healthy |
| [ ] | 024 | Open Adminer at `http://localhost:8080` and log in | S | 5A-09 | Empty database visible |
| [ ] | 025 | `uv add sqlalchemy "psycopg[binary]" alembic`; `helios/common/db.py` with `get_engine()` reading `.env` | S | 5A-09 | Test runs `SELECT 1` |
| [ ] | 026 | `helios/common/config.py`: `load_config(path, Model)` = YAML → pydantic | S | 5A-10 | Test loads a sample YAML |
| [ ] | 027 | `config_hash(model)` = sha256 of canonical JSON (sorted keys) | S | 5A-10 | Tests: key order does not change hash; value change does |
| [ ] | 028 | `helios/common/lineage.py`: `RunContext.capture(config, data_snapshot_id, seed)` with git commit + dirty-tree flag | S | 5A-13 | Test; reported runs refuse a dirty tree |
| [ ] | 029 | `helios/common/seed.py`: `set_seed(seed)` for `random` and `numpy` | S | 5A-13 | Test: same seed → same random numbers |
| [ ] | 030 | `docs/decisions/ADR-000-template.md` (Context · Decision · Alternatives · Consequences · Date) | Q | 5A-12 | Merged |
| [ ] | 031 | **ADR-001** stack = `ARCHITECTURE_AND_TECH_STACK.md`; all three approve in PR | Q | 5A-12 | Merged with 2 approvals |
| [ ] | 032 | **ADR-002 Fitness formula:** `Fitness = Sharpe × sqrt(|annual_return| / max(turnover, floor))`; choose `floor`; include a worked numeric example | Q | 5A-12 | Merged |
| [ ] | 033 | **ADR-003 horizon families:** H-HOURLY (8,760 periods/yr), H-MINUTE (525,600); every result also reports **daily-aggregated Sharpe** | Q | 5A-12 | Merged |
| [ ] | 034 | **ADR-004 split dates** (hourly and minute, with embargo). The table in 5thSem_Plan.md is a starting point | Q | 5A-12 | Merged |
| [ ] | 035 | **ADR-005 fees:** read the Binance spot fee page; record maker/taker bps and slippage assumption with date checked | Q | 5A-12 | Merged |
| [ ] | 036 | Config files + pydantic models: `configs/gates_v1.yaml` (G1–G6), `configs/universe.yaml` (BTC, ETH, SOL, BNB, XRP USDT), `configs/fees.yaml`, `configs/splits.yaml` | Q | 5A-12 | All load via `load_config` in a test |
| [ ] | 037 | FI-2010: `helios/ml/fi2010.py` unzip + read one file into a numpy matrix; check shape (rows = 149, columns = events) | M | 5L-07 | Test on the train file prints shape |
| [ ] | 038 | FI-2010: split matrix into LOB (rows 0–39), features (40–143), labels (last 5); label horizons k = 10, 20, 30, 50, 100 | M | 5L-07 | Unit test on shapes and label values ∈ {1, 2, 3} |

**Checkpoint 3:** Postgres running; config and lineage helpers merged; 5 ADRs approved; FI-2010 loads.

---

## Sprint 4 (Week 4): Download and clean bar data

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 039 | `scripts/download_binance.py`: CLI args `--symbol --interval --start YYYY-MM --end YYYY-MM`; builds monthly URLs | S | 5B-01 | `--dry-run` prints correct URLs |
| [ ] | 040 | Add download with retries; skip file if already present; months that return 404 (before listing) are skipped with a log line | S | 5B-01 | Re-run downloads nothing new |
| [ ] | 041 | Checksum: download `<file>.zip.CHECKSUM`, verify sha256, delete and retry on mismatch | S | 5B-01 | Test with a corrupted file |
| [ ] | 042 | Verify checksums of the BTCUSDT files already in `data/` | S | 5B-01 | All OK |
| [ ] | 043 | Download **1h** for ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT (full history) | S | 5B-02 | 5 coins of 1h data present |
| [ ] | 044 | Check disk (`df -h`), then download **1m** for the 4 other coins, 2024-09 → 2026-08 | S | 5B-03 | 5 × 24 monthly 1m zips |
| [ ] | 045 | `helios/data/binance.py`: `read_klines(zip_path)` → DataFrame with the 12 named columns | S | 5B-04 | Test with a tiny fixture zip in `research/tests/fixtures/` |
| [ ] | 046 | `normalise_ts()`: values ≥ 1e14 are µs, else ms → int64 UTC microseconds | S | 5B-05 | Test with one 2024 row (ms) and one 2025 row (µs) |
| [ ] | 047 | `validate_bars(df)`: prices > 0, high ≥ max(open, close), low ≤ min(open, close), volume ≥ 0 → returns bad rows (never fixes them) | S | 5B-06 | Test with a broken fixture row |
| [ ] | 048 | `find_gaps(df, interval)` + duplicate check on the expected time grid → gaps DataFrame (never fills) | S | 5B-07 | Test: deleted row appears as a gap |
| [ ] | 049 | FI-2010: per-day split exactly like DeepLOB (train days 1–7, test days 8–10), return torch-free numpy arrays | M | 5L-07 | Test on array lengths |
| [ ] | 050 | FI-2010 baseline 1: logistic regression on the 40 LOB columns, horizon k = 10, seeds 0/1/2 | M | 5L-08 | Accuracy + macro-F1 per seed saved to a CSV |

---

## Sprint 5 (Week 5): Parquet, DB schema, registry

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 051 | `scripts/build_bars.py`: zips → read → normalise → validate → write Parquet `data/processed/bars/source=binance/interval=…/symbol=…/year=…/` | S | 5B-08 | Parquet files appear |
| [ ] | 052 | Also write `data/processed/reports/{validation,gaps}_<symbol>_<interval>.parquet` | S | 5B-07 | Reports exist |
| [ ] | 053 | Run `build_bars.py` for 5 coins × 1h and 5 coins × 1m; read the gap report | S | 5B-08 | Gap counts noted in `docs/research/data_quality.md` |
| [ ] | 054 | `helios/data/loader.py`: `load_bars(symbols, interval, start, end)` using DuckDB over Parquet | S | 5B-10 | Test on time filter; 9 years × 5 coins hourly loads in < 5 s |
| [ ] | 055 | Sanity test: resample BTC 1m → 1h and compare with downloaded 1h over the overlap | S | 5B-11 | Mismatch count printed; should be ~0 |
| [ ] | 056 | `uv run alembic init`; `env.py` reads DB URL from `.env` | S | 5C-01 | `alembic upgrade head` runs |
| [ ] | 057 | Migration 001: `instruments`, `data_snapshots`, `experiments` | S | 5C-02 | Tables visible in Adminer |
| [ ] | 058 | Seed `instruments` from `universe.yaml` (symbol, tick size, lot size, first available date) | S | 5B-12 | 5 rows |
| [ ] | 059 | `register_snapshot()`: file list + sha256 + date range → `data_snapshots` row; called at end of `build_bars.py` | S | 5B-09 | Snapshot ids stored |
| [ ] | 060 | `universe_on(date)`: returns only coins already listed on that date | S | 5B-12 | Test: SOL excluded in 2019 |
| [ ] | 061 | Migration 002: `alpha_definitions`, `alpha_results`, `alpha_gate_config`, `test_set_access` | S | 5C-03 | Tables visible |
| [ ] | 062 | Migration 003: triggers that block UPDATE/DELETE on `alpha_definitions` and `alpha_results` | S | 5C-04 | Test: UPDATE raises |
| [ ] | 063 | FI-2010 baseline 2: small MLP (scikit-learn) on the same data, seeds 0/1/2; mean ± std table | M | 5L-08 | Table in `docs/research/fi2010_baselines.md` (measured values only) |

---

## Sprint 6 (Week 6): Registry API + first features

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 064 | `helios/registry/api.py`: `register_definition`, `get_alpha`, `list_alphas` | S | 5C-05 | Tests against the Docker DB |
| [ ] | 065 | `record_result(...)`: refuses rows without `code_commit`, `config_hash`, `data_snapshot_id`, `seed` | S | 5C-05 | Test |
| [ ] | 066 | Status state machine DRAFT → SIMULATED → EVALUATED → PROMOTED / REJECTED / INVALID → RETIRED; illegal moves raise | S | 5C-06 | Hypothesis property test |
| [ ] | 067 | Test-set access log: every TEST access writes a row; the **3rd** access for the same alpha raises | S | 5C-07 | Test |
| [ ] | 068 | `register_experiment(hypothesis, params)`; evaluation functions require an `experiment_id` | S | 5C-08 | Test: run without experiment refused |
| [ ] | 069 | Load `gates_v1.yaml` into `alpha_gate_config` with its hash | S | 5C-03 | Row visible |
| [ ] | 070 | `helios/features/registry.py`: `@feature(name, lookback, warmup, units)` + `FEATURE_SET_VERSION = "v1"` | Q | 5D-01 | Test lists registered features |
| [ ] | 071 | Feature runner: bars DataFrame (one symbol) → features DataFrame + availability mask | Q | 5D-01 | Test on fixture |
| [ ] | 072 | Features: log return over 1, 4, 24 bars | Q | 5D-02 | Hand-calculated test |
| [ ] | 073 | Features: close / rolling mean(12, 48, 168) − 1 | Q | 5D-03 | Test |
| [ ] | 074 | Features: rolling std of returns (24, 168); Parkinson; Garman–Klass | Q | 5D-04 | Tests |
| [ ] | 075 | DeepLOB model skeleton in PyTorch (`uv add torch`), forward pass on a fake batch `(N, 1, 100, 40)` | M | 5L-09 | Output shape (N, 3) |

---

## Sprint 7 (Week 7): Finish features + alpha DSL

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 076 | Features: volume z-score (168), dollar volume | Q | 5D-05 | Tests |
| [ ] | 077 | Features: taker-buy ratio = taker_buy_base / volume, and its z-score | Q | 5D-06 | Tests |
| [ ] | 078 | Features: n_trades z-score, average trade size | Q | 5D-07 | Tests |
| [ ] | 079 | Features: hour-of-day, day-of-week (sin/cos encoded) | Q | 5D-08 | Tests |
| [ ] | 080 | Helpers `zscore(x, w)` and `rank_ts(x, w)` using **trailing windows only** | Q | 5D-09 | Test: value at t unchanged when data after t changes |
| [ ] | 081 | Warm-up masking: values are UNAVAILABLE until the lookback is full | Q | 5D-10 | Test |
| [ ] | 082 | **Causality property test** over every registered feature (random cut point, perturb the future) | Q | 5D-11 | CI green |
| [ ] | 083 | `scripts/build_features.py --interval 1h`: all coins → `data/processed/features/feature_set=v1/interval=1h/` | Q | 5D-12 | Files written |
| [ ] | 084 | Notebook `research/notebooks/01_feature_check.ipynb`: plot a few features for BTC to eyeball sanity | Q | 5D-12 | Plots look sensible |
| [ ] | 085 | `AlphaDefinition` pydantic model + example YAML in `configs/alphas/examples/` | Q | 5E-01 | Loads and registers as DRAFT |
| [ ] | 086 | DSL parser: Python `ast.parse` with a **whitelist** of node types and function names (never `eval`) | Q | 5E-02 | Test: `zscore(ret_1, 24) * -1` parses |
| [ ] | 087 | DeepLOB training loop on FI-2010 (CPU or free GPU), 1 epoch smoke run, seed fixed | M | 5L-09 | Loss decreases on the smoke run |

---

## Sprint 8 (Week 8): Alpha DSL + simulator start

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 088 | DSL evaluator for arithmetic (`+ - * /`, constants, feature names) | Q | 5E-02 | Tests |
| [ ] | 089 | DSL functions: `zscore`, `ts_mean`, `ts_std`, `rank_ts`, `lag(x, k)`, `sign`, `clip`, `where` | Q | 5E-02 | Tests per function |
| [ ] | 090 | Safety checks: negative / zero lag, unknown function or feature, full-sample functions → error | Q | 5E-03 | Tests: forbidden expressions raise |
| [ ] | 091 | Cross-sectional functions `cs_rank`, `cs_demean` across the universe on each timestamp | Q | 5E-04 | Tests |
| [ ] | 092 | Final output clipped to [−1, 1]; scale convention stored | Q | 5E-05 | Test |
| [ ] | 093 | Count free parameters (numeric constants + window sizes) | Q | 5E-07 | Stored in definition |
| [ ] | 094 | Baseline YAMLs: **B0** `sign(ret_24)` · **B1** `-zscore(ret_1, 168)` · **B2** `zscore(taker_buy_ratio, 168)`; register as DRAFT | Q | 5E-06 | 3 rows in DB |
| [ ] | 095 | Simulator: align alpha with forward return; `pos_t = clip(alpha_t / scale)`; **return uses pos_{t−1}** | Q | 5F-01 | Hand-calculated 5-bar test |
| [ ] | 096 | Cost model from `fees.yaml`: `turnover × cost_bps`; gross and net P&L series | Q | 5F-02 | Test |
| [ ] | 097 | Migration 004: `strategies`, `risk_limits`, `orders`, `fills`, `positions_snapshot`, `pnl_snapshots`, `risk_events`, `backtest_runs`, `audit_events` | S | 5C-09 | Tables visible |
| [ ] | 098 | Write `docs/decisions/ADR-006-interfaces.md` describing the 5 interfaces from the architecture doc §8 | S | 5H-01 | Merged |
| [ ] | 099 | DeepLOB full training on FI-2010 (k = 10) for 3 seeds on free GPU; save checkpoints outside git | M | 5L-09 | Accuracy / F1 per seed recorded |

**Checkpoint 8:** features for hourly data exist; baseline alphas registered; simulator produces P&L.

---

## Sprint 9 (Week 9): Metrics, gates and leakage tests

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 100 | Metrics: total/annual return, volatility, per-period Sharpe | Q | 5F-03 | Tests on a known series |
| [ ] | 101 | Metrics: **daily-aggregated Sharpe**, turnover, max drawdown + duration, hit rate | Q | 5F-03 | Tests |
| [ ] | 102 | Fitness from ADR-002 | Q | 5F-04 | Test reproduces the ADR's worked example |
| [ ] | 103 | IC: time-series IC per coin; cross-sectional IC over 5 coins; IC-IR | Q | 5F-05 | Tests |
| [ ] | 104 | Cost-sensitivity sweep 0.5×, 1×, 2×, 3×, 4× | Q | 5F-06 | Curve returned |
| [ ] | 105 | Stability by month (mean, min, % months > 0) + regime split by volatility terciles | Q | 5F-07 | Tests |
| [ ] | 106 | Validity checks → **INVALID**: constant alpha, too few rows, NaNs after warm-up | Q | 5F-08 | Tests |
| [ ] | 107 | Splits with embargo from `splits.yaml`; metrics per split; TEST goes through the access counter (step 067) | Q | 5F-09 | Tests |
| [ ] | 108 | Gate evaluator G1–G6 → per-gate PASS/FAIL + threshold + `gate_config_hash` | Q | 5F-10 | Test: crafted series passes/fails each gate |
| [ ] | 109 | **Noise alpha** test: random alpha over 20 seeds → mean Sharpe ≈ 0 | Q | 5F-11 | Test in CI |
| [ ] | 110 | **Future-peek alpha** test: alpha = next return → absurdly high Sharpe (proves alignment is right) | Q | 5F-11 | Test in CI |
| [ ] | 111 | Leakage suite: constant alpha → INVALID; shifting features one bar later must make results worse; mark `@pytest.mark.leakage`; separate **required** CI job | Q | 5F-12 | Required check on `main` |
| [ ] | 112 | Record types in `helios/common/types.py`: Bar, AlphaValue, OrderAction, NewOrder, Order, ExecutionReport, Fill, Position, PnLSnapshot, RiskDecision + reason-code enum | S | 5H-02 | mypy clean |
| [ ] | 113 | Interfaces as `typing.Protocol` in `helios/common/interfaces.py` (MarketDataSource, AlphaModel, Strategy, RiskEngine, ExecutionVenue) | S | 5H-01 | mypy clean |
| [ ] | 114 | Hourly features also for the ML dataset: `helios/ml/dataset.py` builds X (features at t), y (forward return over h) | M | 5L-01 | Test on fixture |
| [ ] | 115 | Purge/embargo: drop samples whose label window crosses a split boundary | M | 5L-01 | Test: no crossing labels |

---

## Sprint 10 (Week 10): First evaluations + backtest core

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 116 | `helios/sim/evaluate.py`: `evaluate(alpha_id, split, experiment_id)` → metrics → gates → `record_result` with lineage | Q | 5F-13 | One call stores a result row |
| [ ] | 117 | `scripts/evaluate_alphas.py`: many alphas in a process pool | Q | 5F-14 | 3 baselines evaluated in one command |
| [ ] | 118 | Report generator → `reports_out/<alpha_id>/report.html`: equity, drawdown, cost curve, monthly stability, gate table | Q | 5F-15 | Report opens in browser |
| [ ] | 119 | Evaluate B0–B2 on TRAIN + VALID (hourly); read the reports | Q | 5G-01 | 3 results stored |
| [ ] | 120 | Historical bar `MarketDataSource`: replays Parquet bars in time order across symbols | S | 5H-03 | Iterates 1 year hourly for 5 coins |
| [ ] | 121 | Event loop: at bar close t, strategy decides; orders can act only from **bar t+1 open** | S | 5H-04 | Test: no fill on the decision bar |
| [ ] | 122 | Strategy v1 part 1: alpha → target notional per coin (config: capital, max weight) | S | 5H-05 | Test |
| [ ] | 123 | Strategy v1 part 2: target − current position → order size; **no order if change < rebalance threshold** | S | 5H-05 | Test: small alpha change → no order |
| [ ] | 124 | Risk v1 part 1: check-chain framework (ordered list of checks, first failure rejects, reason codes, fail-closed on exception) | S | 5H-06 | Test: exception inside a check → REJECT |
| [ ] | 125 | ML baseline: ridge + logistic regression on hourly features, fixed seed; validation metrics logged | M | 5L-02 | Metrics saved |
| [ ] | 126 | ML: LightGBM (`uv add lightgbm`) with fixed seed and early stopping on VALID | M | 5L-02 | Metrics saved |

---

## Sprint 11 (Week 11): Hourly research round + risk / OMS

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 127 | Pre-register 8–10 hourly hypotheses with `register_experiment` **before** running anything | Q | 5G-02 | Rows in `experiments` |
| [ ] | 128 | Write them as DSL YAML files in `configs/alphas/hourly/` | Q | 5G-03 | Files merged |
| [ ] | 129 | Evaluate all on VALID; change only on VALID; every version stored (including bad ones) | Q | 5G-04 | Registry shows all versions |
| [ ] | 130 | Risk v1 part 2: max order size + price band vs trailing median price | S | 5H-06 | Tests with reason codes |
| [ ] | 131 | Risk v1 part 3: **projected position** limit (current + open orders + new) and exposure limit | S | 5H-06 | Test: the "1800 + 150 + 200 > 2000" example rejects |
| [ ] | 132 | Risk v1 part 4: daily loss limit + kill switch flag; trips write `risk_events` | S | 5H-07 | Test: zero orders after trip |
| [ ] | 133 | OMS part 1: `order_id` generator, `client_order_id` idempotency (duplicate submit returns original) | S | 5H-08 | Test |
| [ ] | 134 | OMS part 2: order state machine (CREATED → PENDING_NEW → ACCEPTED → PARTIALLY_FILLED → FILLED / CANCELLED / REJECTED) | S | 5H-08 | Illegal transition test |
| [ ] | 135 | OMS part 3: hypothesis property test: `filled + remaining == qty` always | S | 5H-08 | Test passes |
| [ ] | 136 | ML: calibrate probabilities on VALID only (isotonic) | M | 5L-03 | Calibration plot saved |
| [ ] | 137 | ML: prediction → alpha (edge − **cost**, trailing z-score, clip) | M | 5L-04 | AlphaValue series produced |

---

## Sprint 12 (Week 12): Promotion decision + paper venue + ledger

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 138 | Search-effort summary: how many tried, best vs baselines | Q | 5G-05 | Table ready |
| [ ] | 139 | TEST run for at most 2–3 best candidates (the counter enforces ≤ 2 accesses) | Q | 5G-06 | TEST results stored |
| [ ] | 140 | Set PROMOTED / REJECTED; write `docs/research/hourly_round1.md` including failures and honest limits | Q | 5G-07 | Note merged |
| [ ] | 141 | Paper venue part 1: implements `ExecutionVenue`; market order fills at next bar open ± slippage bps; `is_simulated = True` | S | 5H-09 | Tests |
| [ ] | 142 | Paper venue part 2: limit order fills only if the next bar **trades through** the limit price; maker vs taker fee | S | 5H-09 | Tests |
| [ ] | 143 | P&L ledger: average cost, realised, unrealised, fees; **booked only on fills** (spec §24.5) | S | 5H-10 | Tests: open, add, reduce, flip positions |
| [ ] | 144 | Ledger reconciliation invariant checked at every snapshot; hypothesis property test | S | 5H-10 | Test passes |
| [ ] | 145 | ML: register ML alpha (provenance = ML) and evaluate through the **same** simulator + gates | M | 5L-05 | ML result rows stored |
| [ ] | 146 | ML: shuffled-label control → performance ≈ chance; add to leakage suite | M | 5L-06 | Required CI job includes it |

---

## Sprint 13 (Week 13): Backtest end-to-end + minute stage start

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 147 | Hand-verified scenario: 10 bars, 3 trades calculated in a spreadsheet (commit the sheet as CSV) | S | 5H-11 | CSV merged |
| [ ] | 148 | Test: backtest of that scenario equals the spreadsheet exactly | S | 5H-11 | Test passes |
| [ ] | 149 | Backtest runner: config → run → `backtest_runs`, orders, fills, P&L in DB; mode = BACKTEST | S | 5H-12 | One command runs a backtest |
| [ ] | 150 | Backtest report: gross/net P&L, drawdown, exposure, trades, fees, per-coin P&L | S | 5H-13 | Report generated |
| [ ] | 151 | Backtest the promoted hourly alpha (or best candidate if none passed) | S+Q | 5H-14 | Report + short note |
| [ ] | 152 | `build_features.py --interval 1m` for all coins (**no code change**, only config) | Q | 5I-01 | Minute features written |
| [ ] | 153 | H-MINUTE config: periods_per_year 525,600, minute split dates, gate config | Q | 5I-02 | Config merged |
| [ ] | 154 | Live data part 1: Binance public WebSocket 1m kline stream (`uv add websockets`), prints closed bars; **no API keys** | S | 5J-01 | Prints bars for 10 minutes |
| [ ] | 155 | Streamlit (`uv add streamlit`) page 1: alpha registry table + link to each report | M | 5J-04 | Page shows all alphas + statuses |

---

## Sprint 14 (Week 14): Minute research + live paper trading

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 156 | Pre-register and evaluate minute baselines + 6–8 hypotheses on VALID | Q | 5I-03 | Results stored |
| [ ] | 157 | Cost reality check: gross edge vs fees; cost-sensitivity curves for minute alphas | Q | 5I-05 | Plot saved |
| [ ] | 158 | ML minute alpha through the same pipeline | M | 5I-04 | ML minute result stored |
| [ ] | 159 | Live data part 2: reconnect on disconnect + gap detection on live bars | S | 5J-01 | Pull network cable test → reconnects, gap logged |
| [ ] | 160 | PAPER runner: live bars → same strategy / risk / OMS / paper venue as backtest; mode = PAPER | S | 5J-02 | Paper orders + fills appear in DB |
| [ ] | 161 | Streamlit page 2: paper P&L, positions, open orders, risk state, **PAPER / is_simulated badge** | M | 5J-05 | Page updates live |
| [ ] | 162 | Kill switch button on dashboard → writes `audit_events` row; risk blocks orders | S+M | 5J-06 | Test: pressing it stops orders |

---

## Sprint 15 (Week 15): Final minute decision + 7-day paper run

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 163 | TEST for the best 2 minute candidates; promote / reject | Q | 5I-06 | Results stored |
| [ ] | 164 | Backtest the best minute alpha | Q+S | 5I-06 | Report |
| [ ] | 165 | `docs/research/minute_round1.md`: hourly vs minute comparison using daily-aggregated Sharpe | Q | 5I-07 | Note merged |
| [ ] | 166 | Run the PAPER runner on an always-on machine (spare PC or small VM) with `docker compose` | S | 5J-03 | Runs unattended for 24 h |
| [ ] | 167 | Start the **7-day** paper run with the promoted minute (or hourly) alpha | S | 5J-07 | Day 1 records present |
| [ ] | 168 | *(Optional, recommended)* Start a simple WebSocket order-book recorder for BTC/ETH to collect millisecond data for the 6th sem | S | 6A-06 | Daily files appearing |
| [ ] | 169 | Reproducibility check: pick a random stored result, re-run from its lineage, get identical numbers | Q | 5K-01 | Identical output |

---

## Sprint 16 (Week 16): Close the semester

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 170 | After 7 days: paper-vs-backtest comparison over the same days; explain differences | Q | 5J-08 | Report merged |
| [ ] | 171 | Check branch protection: CI, leakage suite and property tests are required checks | S | 5K-02 | Screenshot in `docs/` |
| [ ] | 172 | Update spec/SRS with decisions made this semester (crypto data, horizon stages, stack, Fitness) | All | 5K-03 | Docs updated |
| [ ] | 173 | 5th-sem report (template sections) with **measured results only** + negative results | All | 5K-04 | Report ready |
| [ ] | 174 | Demo video: data → features → alpha → gates → backtest → live paper dashboard → kill switch | All | 5K-04 | Video recorded |
| [ ] | 175 | Write `6thSem/carryover_from_5th.md` with any unfinished step numbers | All | 5K-05 | Merged |

**Final checkpoint:** every box in the "Exit criteria" of [5thSem_Plan.md](5thSem_Plan.md) is ticked.

---

## Summary by person

| Owner | Main path through the semester |
|---|---|
| **S** | Setup (010–029) → data (039–062) → registry (064–069) → trading types (097–113) → backtester, risk, OMS, paper venue, ledger (120–150) → live paper trading (154–168) |
| **Q** | Decisions (030–036) → features (070–084) → alpha DSL (085–094) → simulator + gates + leakage suite (095–119) → hourly research (127–140) → minute research (152–165) → reproducibility and paper comparison (169–170) |
| **M** | FI-2010 (037–050, 063) → DeepLOB (075–099) → ML dataset + models (114–137) → ML alphas through gates (145–158) → dashboard (155–162) |

If a sprint slips, move its unfinished steps to the next week but **keep the order**. Never skip ahead to a step whose "Plan ID" depends on an unfinished one.
