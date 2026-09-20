# 5th Semester: Step-by-Step Work Order

This file turns [5thSem_Plan.md](5thSem_Plan.md) into **one numbered sequence of small steps** (each ≈ 2–6 hours).
Follow the numbers in order.

- **Plan ID** points to the task in the plan, which has more detail.
- **Owner:** **Q** Quant researcher · **S** Systems engineer · **M** ML engineer · **All** everyone.
- **Team (step 009):** **Q = Abhishek Kumar** (fixed). **S and M are shared by all three: Abhishek Kumar, Anuj Sharma, Indra Shikari**. At each Monday meeting, write the chosen name next to every S/M step.
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
| [x] | 001 | Check free space: PowerShell → `Get-PSDrive C` | All | 5A-01 | You know the free GB *(done 2026-09-12: 22.3 GB free, C: is the only drive)* |
| [x] | 002 | Free space to **≥ 40 GB**: remove unused apps, run Storage Sense, move big personal files to another drive | All | 5A-01 | `Get-PSDrive C` shows ≥ 40 GB free *(done 2026-09-12: 36.5 GB free; accepted because WSL Ubuntu + Docker are already installed; optional +5 GB by deleting the VS Code `ipch` cache)* |
| [x] | 003 | Admin PowerShell: `wsl --install -d Ubuntu-24.04` → reboot → create Linux username/password | All | 5A-02 | Ubuntu terminal opens *(done 2026-09-12: already installed: Ubuntu 24.04.3 LTS, WSL 2.5.10, kernel 6.6.87, user `abhi` in sudo + docker groups)* |
| [x] | 004 | In Ubuntu: `sudo apt update && sudo apt upgrade -y && sudo apt install -y build-essential git curl unzip` | All | 5A-02 | `git --version` works *(done 2026-09-12: gcc/g++ 13.3.0, make 4.3, git 2.43.0, curl 8.5.0, unzip OK, build-essential installed, 0 upgradable packages)* |
| [x] | 005 | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` → restart terminal → `uv python install 3.12` | All | 5A-02 | `uv --version` and `uv python list` show 3.12 *(done 2026-09-12: uv 0.12.13 was already installed at ~/.local/bin/uv; Python 3.12.14 installed via uv; works in a fresh login shell)* |
| [x] | 006 | Git identity: `git config --global user.name "…"` and `user.email "…"`; create SSH key `ssh-keygen -t ed25519`; add public key to GitHub | All | 5A-02 | `ssh -T git@github.com` greets you *(done 2026-09-12 in WSL Ubuntu: Abhishek Kumar / abhishek.cse.dev@gmail.com; ed25519 key added to GitHub; "Hi AbhishekKumar-cse! You've successfully authenticated")* |
| [x] | 007 | Install Docker Desktop → Settings → Resources → WSL integration → enable Ubuntu-24.04 | All | 5A-03 | `docker run hello-world` works **inside Ubuntu** *(done 2026-09-12: 4.73.0 crashed on stale `dockerInference` socket → reinstalled Docker Desktop 4.90.0; WSL integration ON for Ubuntu; Docker AI OFF; client/server 29.7.2, Compose v5.5.1; hello-world OK)* |
| [x] | 008 | Install VS Code + extensions: WSL, Python, Ruff, Docker. Open Ubuntu folder with `code .` | All | — | VS Code shows "WSL: Ubuntu" in the corner *(done 2026-09-12: VS Code 1.137.0; Windows side: WSL 0.104.3, Python 2026.4.0, Ruff 2026.80.0 (new), Container Tools 2.5.0; WSL side (server 645f29cc): Python 2026.4.0 + Pylance 2026.3.1 + debugpy 2026.6.0 (updated), Ruff 2026.80.0 + Container Tools 2.5.0 (new); VS Code window connected to WSL: Ubuntu)* |
| [x] | 009 | Team meeting: decide who is **Q**, **S**, **M** | All | 5A-11 | Names written down *(done 2026-09-12: **Q = Abhishek Kumar (fixed)**; **S and M = shared by all three: Abhishek Kumar, Anuj Sharma, Indra Shikari**, no fixed split, assigned task-by-task in the Monday meeting)* |

**Checkpoint 1:** all three laptops can run Ubuntu, uv, git and Docker.

---

## Sprint 2 (Week 2): Repository and project skeleton

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [ ] | 010 | Create **private** GitHub repo `helios`; add teammates; protect `main` (require PR + 1 review + passing checks) | S | 5A-04 | Teammates accepted invites *(in progress 2026-09-12: repo `AbhishekKumar-cse/helios-trading-engine` exists and is now **private** ✅; pending: invite Anuj + Indra, GitHub Student Developer Pack (free Pro, needed for branch protection on private repos), then protect `main`)* |
| [x] | 011 | Clone into the **Linux home folder**: `cd ~ && git clone git@github.com:<org>/helios.git`. Do **not** put the repo in OneDrive: it is slow from WSL and sync breaks git | S | 5A-04 | `~/helios` exists *(done 2026-09-12, then **changed by team decision**: the working copy is the **OneDrive folder `C:\Users\bit\OneDrive\Desktop\helios`** (already a git repo with `origin` → `AbhishekKumar-cse/helios-trading-engine`). The test clone in Ubuntu `~/helios` is not used and is removed by the user)* |
| [x] | 012 | Create the folder skeleton from `ARCHITECTURE_AND_TECH_STACK.md` §7: `docs/{decisions,spec,reports,research}`, `configs/`, `research/helios/`, `research/tests/`, `dashboards/streamlit/`, `infra/`, `scripts/`, `data/`, `.github/workflows/` (add `.gitkeep` files) | S | 5A-04 | `tree -L 2` matches the doc *(done 2026-09-12 in the OneDrive working copy: 11 folders created with `.gitkeep`; `data/` already existed and stays gitignored; later-semester folders `core/ cluster/ spec/tla/ proto/` intentionally not created yet)* |
| [x] | 013 | `.gitignore`: `data/`, `.env`, `.venv/`, `__pycache__/`, `*.parquet`, `*.zip`, `*.csv.gz`, `reports_out/` | S | 5A-04 | `git status` stays clean after copying data *(done 2026-09-12: all 8 required rules present; added `.env.*` (keeps `.env.example`), `*.egg-info/`, `.coverage`, `htmlcov/`, and an exception so `research/tests/fixtures/**` zips/parquet ARE committed; 22/22 path checks passed; 0 data files visible to git)* |
| [x] | 014 | Copy documents: spec `.md` + Knowledge Base PDF → `docs/spec/`; SRS reports + PDF → `docs/reports/`; `ARCHITECTURE_AND_TECH_STACK.md` → repo root; `5thSem/ 6thSem/ 7thSem/` → repo root. Source is `/mnt/c/Users/bit/OneDrive/Desktop/helios/` | S | 5A-05 | Docs committed and pushed *(done 2026-09-12 in the OneDrive working copy: **moved** (not copied) spec `.md` + Knowledge Base PDF → `docs/spec/`; `HELIOS_SRS.pdf`, 4 report `.docx` (incl. identical `_2`/`_3`) + `SRS-SDS format.docx` → `docs/reports/`; architecture doc + semester plans already at root. Commit + push is the user's action)* |
| [x] | 015 | Copy downloaded data: `cp -r /mnt/c/Users/bit/OneDrive/Desktop/helios/data ~/helios/` | S | 5A-05 | `du -sh ~/helios/data` ≈ 339 MB; not in git *(done 2026-09-12: no copy needed, the OneDrive folder is the only working copy; `helios\data\` verified: 338.1 MB / 140 files, all stored locally, **139/139 archives pass integrity test**, 1h 2017-08→2026-08, 1m 2024-09→2026-08; git tracks/shows 0 data files)* |
| [x] | 016 | Python project in repo root: `uv init --package --name helios`; set source dir to `research/helios`; add deps: `uv add numpy pandas pyarrow duckdb pydantic pyyaml` and dev deps `uv add --dev pytest hypothesis ruff mypy pre-commit` | S | 5A-06 | `uv sync` succeeds *(done 2026-09-12: hand-written `pyproject.toml` (hatchling, package = `research/helios`), `.python-version` = 3.12, `research/helios/__init__.py` (from step 017) created early; **venv kept outside OneDrive** at `~/.venvs/helios` via `UV_PROJECT_ENVIRONMENT` in `~/.bashrc` + `~/.profile`; `uv.lock` = 37 packages; Python 3.12.14, numpy 2.5.3, pandas 3.0.5, pyarrow 25.0.1, duckdb 1.5.5, pydantic 2.13.5, pyyaml 6.0.3; dev: pytest 9.1.1, hypothesis 6.168.0, ruff 0.16.7, mypy 2.3.1, pre-commit 4.6.2; `uv sync --locked` clean)* |
| [x] | 017 | Add `research/helios/__init__.py` and `research/tests/test_smoke.py` (`assert 1 + 1 == 2`) | S | 5A-06 | `uv run pytest` → 1 passed *(done 2026-09-12: `__init__.py` created in step 016; `test_smoke.py` checks `1 + 1 == 2` and `helios.__version__ == "0.1.0"`; added `[tool.pytest.ini_options] testpaths = ["research/tests"]` to `pyproject.toml`; `uv run pytest -v` → **1 passed in 2.14s** on Python 3.12.14 / pytest 9.1.1; `.hypothesis/` added to `.gitignore`)* |
| [x] | 018 | Configure ruff (line length 100, import sorting) and mypy (strict for `helios/`) in `pyproject.toml` | S | 5A-06 | `uv run ruff check .` and `uv run mypy research/helios` clean *(done 2026-09-12: ruff line-length 100, py312, rules E/W/F/I/B/UP, isort first-party `helios`, `extend-exclude = ["*.md"]` so docs are never reformatted; mypy `strict = true`, `mypy_path = "research"`, pydantic plugin; results: `ruff check .` All checks passed, `ruff format --check .` 2 files already formatted, `mypy research/helios` Success, pytest 1 passed)* |
| [x] | 019 | `.pre-commit-config.yaml`: ruff, ruff-format, end-of-file-fixer, trailing-whitespace, **gitleaks**; `uv run pre-commit install` | S | 5A-07 | Committing a file with `AWS_SECRET_ACCESS_KEY=abc123…` is blocked *(done 2026-09-12: hooks = pre-commit-hooks v6.0.0 (end-of-file, trailing-whitespace, check-yaml, check-toml, large files >1 MB), ruff-pre-commit v0.16.7 (ruff-check --fix, ruff-format), local gitleaks hook using official **gitleaks v8.30.1** binary in `~/.local/bin` (sha256 verified); `docs/spec` + `docs/reports` excluded; hook installed at `.git/hooks/pre-commit`; all 8 hooks **Passed** on every non-ignored file; fake-secret test (outside repo) → gitleaks found `github-pat`, exit 1 = commit would be blocked; real project scan: no secrets. **Team rule: commit from Ubuntu terminal / VS Code "WSL: Ubuntu"** (Windows PowerShell commits fail: pre-commit not installed there))* |
| [x] | 020 | `.github/workflows/ci.yml`: checkout → install uv → `uv sync` → ruff → mypy → pytest | S | 5A-08 | Green check on a PR *(done 2026-09-12: `ci.yml` triggers on push to `main` + every pull request; `actions/checkout@v7`, `astral-sh/setup-uv@v10.1.0` (exact tag, setup-uv has no moving `v10` tag; first run failed on this and was fixed) pinned to uv 0.12.13 with cache; steps `uv sync --locked` → `ruff check` → `ruff format --check` → `mypy research/helios` → `pytest -v`; **GitHub Actions "lint, types, tests" is green ✅** (DB test skips in CI, no `.env`))* |
| [x] | 021 | `docs/TEAM.md`: names + roles, module owners, branch naming, commit format, PR rules, weekly routine | All | 5A-11 | Merged *(done 2026-09-12: `docs/TEAM.md` written: team + roles (Q = Abhishek fixed; S/M shared by all three), module owner table 5A–5L, work rules (commit only from Ubuntu/VS Code WSL, venv outside synced folders, `uv sync`/`uv add`), branch naming `<taskID>-<desc>`, commit format, PR rules, never-commit list, weekly routine, research-integrity rules, new-laptop setup checklist. **On `main` via commit `79d9f14`**)* |
| [ ] | 022 | Every member clones the repo, runs `uv sync && uv run pytest` | All | — | Works on all 3 laptops *(in progress 2026-09-12: **Abhishek's laptop ✅**: `uv sync --locked` exit 0, `pytest` 1 passed; GitHub `main` (`79d9f14`) contains everything a fresh clone needs (`pyproject.toml`, `uv.lock`, `.python-version`, `.pre-commit-config.yaml`, `ci.yml`, `helios/__init__.py`, `test_smoke.py`, `docs/TEAM.md`). **Pending: Anuj ☐, Indra ☐** (accept invite → follow `docs/TEAM.md` §10 → clone → `uv sync && uv run pytest`))* |

**Checkpoint 2:** a PR from each member has been reviewed and merged with green CI.

---

## Sprint 3 (Week 3): Database, config, lineage + decisions

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [x] | 023 | `infra/docker-compose.yml`: `postgres:16` (volume, healthcheck) + `adminer`; `.env.example` with `POSTGRES_USER/PASSWORD/DB/PORT`; real `.env` is gitignored | S | 5A-09 | `docker compose up -d` → both containers healthy *(done 2026-09-12: `infra/docker-compose.yml` with `postgres:16-alpine` (PostgreSQL **16.15**, volume `helios_helios_pgdata`, `pg_isready` healthcheck) + `adminer:5` (php healthcheck, waits for healthy Postgres); ports bound to **127.0.0.1** only (5432, 8080); `.env.example` committed template; private `.env` with random 24-char password (gitignored); result: **helios-postgres healthy, helios-adminer healthy**, `select current_user, current_database()` → `helios|helios`, Adminer HTTP 200. Start: `docker compose --env-file .env -f infra/docker-compose.yml up -d`)* |
| [x] | 024 | Open Adminer at `http://localhost:8080` and log in | S | 5A-09 | Empty database visible *(done 2026-09-12: user logged in to Adminer 5.5.1 (System PostgreSQL, server `postgres`, user `helios`, database `helios`, password from `.env`); empty `helios` database visible; both containers still healthy; no failed-login entries in the Postgres log)* |
| [x] | 025 | `uv add sqlalchemy "psycopg[binary]" alembic`; `helios/common/db.py` with `get_engine()` reading `.env` | S | 5A-09 | Test runs `SELECT 1` *(done 2026-09-12: added SQLAlchemy 2.0.52, psycopg[binary] 3.3.5, Alembic 1.20.0 + pydantic-settings 2.15.0 (reads `.env`, password kept as `SecretStr`); `research/helios/common/db.py`: `DatabaseSettings` (POSTGRES_* vars), `get_settings()`, `get_engine()` (psycopg driver, `pool_pre_ping`); `research/tests/test_db.py`: `test_select_one` (**passed against the running Postgres**; skips when no DB settings, e.g. CI) + `test_password_is_never_shown`; mypy strict clean (3 files), pytest **3 passed**, ruff clean)* |
| [x] | 026 | `helios/common/config.py`: `load_config(path, Model)` = YAML → pydantic | S | 5A-10 | Test loads a sample YAML *(done 2026-09-12: `research/helios/common/config.py` with `load_config(path, Model)` (`yaml.safe_load` → pydantic `model_validate`), `ConfigError` for missing file / invalid YAML / non-mapping top level / invalid values, `HeliosConfig` base (`extra="forbid"` catches typos, `frozen=True` read-only); added dev dep `types-pyyaml`; `research/tests/fixtures/sample_config.yaml` + `research/tests/test_config.py` (10 tests: sample loads, str path, wrong type, unknown key, missing key, missing file, invalid YAML, empty/list top level, frozen); ruff + mypy strict clean, pytest **13 passed**)* |
| [x] | 027 | `config_hash(model)` = sha256 of canonical JSON (sorted keys) | S | 5A-10 | Tests: key order does not change hash; value change does *(done 2026-09-13: `canonical_json()` = `model_dump(mode="json")` → `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`; `config_hash()` = SHA-256 hex (64 chars); 6 tests pass: exact canonical text, stable 64-hex hash, **key order irrelevant**, formatting/comments irrelevant (0.70 = 0.7), **value change changes hash**, list order changes hash. Also added pytest `--tb=short` so failure reports never print function arguments that may hold secrets)* |
| [x] | 028 | `helios/common/lineage.py`: `RunContext.capture(config, data_snapshot_id, seed)` with git commit + dirty-tree flag | S | 5A-13 | Test; reported runs refuse a dirty tree *(done 2026-09-18: `research/helios/common/lineage.py`: frozen `RunContext` (code_commit, dirty, config_hash, data_snapshot_id, seed, created_at UTC) with `capture(config, data_snapshot_id, seed, *, reported=False, repo=PROJECT_ROOT)`; `git_commit()` = `git rev-parse HEAD`, `git_is_dirty()` = `git status --porcelain` (modified or untracked non-ignored files); `reported=True` raises `LineageError` on a dirty tree; also rejects bad seeds and empty snapshot ids; 13 tests in `research/tests/test_lineage.py`, each on its own temporary git repo; ruff + mypy clean, 31 passed)* |
| [x] | 029 | `helios/common/seed.py`: `set_seed(seed)` for `random` and `numpy` | S | 5A-13 | Test: same seed → same random numbers *(done 2026-09-18: `research/helios/common/seed.py`: `set_seed(seed)` seeds `random` + numpy's global generator and returns a `numpy.random.Generator`; seeds must be integers 0 … 2**32−1 (bools, floats, strings, negatives rejected); 9 tests in `research/tests/test_seed.py`; ruff + mypy clean, 41 passed)* |
| [x] | 030 | `docs/decisions/ADR-000-template.md` (Context · Decision · Alternatives · Consequences · Date) | Q | 5A-12 | Merged *(done 2026-09-18: `docs/decisions/ADR-000-template.md` with a header table (Status, Date, Deciders, Plan task, Replaces), usage rules, and Context · Decision · Alternatives (table) · Consequences · References; `docs/decisions/README.md` explains ADRs and keeps the index; empty-folder `.gitkeep` removed. Counts as merged once committed to `main`)* |
| [x] | 031 | **ADR-001** stack = `ARCHITECTURE_AND_TECH_STACK.md`; all three approve in PR | Q | 5A-12 | Merged with 2 approvals *(done 2026-09-18: `docs/decisions/ADR-001-tech-stack.md`: summarises the architecture doc (priorities, Python/C++/Go/TLA+ split, data, horizon, storage, tooling, runtime, simulated execution, integrity), alternatives table, consequences; **approved by team lead Abhishek Kumar** (team rule: the team lead's approval is sufficient); added to the ADR index)* |
| [x] | 032 | **ADR-002 Fitness formula:** `Fitness = Sharpe × sqrt(|annual_return| / max(turnover, floor))`; choose `floor`; include a worked numeric example | Q | 5A-12 | Merged *(done 2026-09-19: `docs/decisions/ADR-002-fitness-formula.md`: **floor = 0.125** approved by team lead; exact definitions of Sharpe (net, annualised per horizon family), annual_return and turnover (same as G3); 4 worked examples (busy trader 0.949 fail, calm trader 1.386 pass, barely-trades 1.470 pass vs 2.324 without floor, loser −0.566 fail); `cost_stress_sharpe` also reported; alternatives 0.01 / no floor / cost-stress Sharpe; added to ADR index)* |
| [x] | 033 | **ADR-003 horizon families:** H-HOURLY (8,760 periods/yr), H-MINUTE (525,600); every result also reports **daily-aggregated Sharpe** | Q | 5A-12 | Merged *(done 2026-09-20: `docs/decisions/ADR-003-horizon-families.md` approved by team lead: families H-HOURLY 8,760 / H-MINUTE 525,600 (+ H-SECOND 31,536,000 and H-MICRO 315,360,000 defined for later), 365-day UTC year; G1–G3 per family (turnover per decision period); daily-aggregated Sharpe = UTC-day P&L, mean/std × √365, empty days excluded, N/A below 30 days, the only cross-family comparison; worked example; added to ADR index)* |
| [x] | 034 | **ADR-004 split dates** (hourly and minute, with embargo). The table in 5thSem_Plan.md is a starting point | Q | 5A-12 | Merged *(done 2026-09-20: `docs/decisions/ADR-004-split-dates.md` approved by team lead; UTC inclusive dates checked against data on disk. HOURLY TRAIN 2018-01-01→2022-12-31 · 7-day embargo · VALID 2023-01-08→2024-06-30 · 7-day embargo · TEST 2024-07-08→2026-08-31. MINUTE TRAIN 2024-09-01→2025-08-31 · 1-day embargo · VALID 2025-09-02→2026-02-28 · 1-day embargo · TEST 2026-03-02→2026-08-31. Rules: embargo ≥ horizon, labels never cross a boundary, TEST ≤ 2 uses, date changes need a new ADR; added to ADR index)* |
| [x] | 035 | **ADR-005 fees:** read the Binance spot fee page; record maker/taker bps and slippage assumption with date checked | Q | 5A-12 | Merged *(done 2026-09-20: `docs/decisions/ADR-005-fees-and-slippage.md` approved by team lead; Binance fee page checked 2026-09-20 (VIP 0: 0.100 % maker / 0.100 % taker; 0.075 % with BNB). Decision: **10 bps** maker/taker (no BNB discount); slippage per side **2 bps** BTC/ETH, **5 bps** SOL/BNB/XRP (assumption, to be checked vs paper trading, step 170); simulator cost = taker fee + slippage = 12 / 15 bps one side; limit orders pay maker fee, no slippage; changes need a new ADR; added to ADR index)* |
| [x] | 036 | Config files + pydantic models: `configs/gates_v1.yaml` (G1–G6), `configs/universe.yaml` (BTC, ETH, SOL, BNB, XRP USDT), `configs/fees.yaml`, `configs/splits.yaml` | Q | 5A-12 | All load via `load_config` in a test *(done 2026-09-20: `configs/gates_v1.yaml` (G1 Sharpe>1, G2 Fitness>1 floor 0.125, G3 1–70 %, G4 out-of-sample, G5 >50 % months Sharpe>0, G6 Sharpe>0 at 2× cost), `configs/universe.yaml` (5 USDT coins), `configs/fees.yaml` (10 bps fees, 2/5 bps slippage, checked_on 2026-09-20, source URL), `configs/splits.yaml` (hourly + minute splits, embargo 7/1 days); models in `research/helios/common/project_config.py` (validate turnover range, symbols, non-negative slippage, chronological splits with exact embargo gaps, known horizon families) + `load_gates/universe/fees/splits`; 10 tests in `research/tests/test_project_config.py` check every value against ADR-002…005; ruff + mypy clean, 51 passed)* |
| [x] | 037 | FI-2010: `helios/ml/fi2010.py` unzip + read one file into a numpy matrix; check shape (rows = 149, columns = events) | M | 5L-07 | Test on the train file prints shape *(done 2026-09-20: `research/helios/ml/fi2010.py`: `list_files()`, `read_matrix(member)` reads straight from `data/fi2010/FI2010_DeepLOB_data.zip` (no extraction into OneDrive) with `np.loadtxt`, checks 149 rows, ≥ 1 event, no NaN/inf, raises `FI2010Error`; measured shapes: **train (149, 254,750)** 304 MB in 16.9 s, test day 8 (149, 55,478), day 9 (149, 52,172), day 10 (149, 31,937); 7 tests in `research/tests/test_fi2010.py` (6 on a fake zip, 1 on the real day-10 file, skipped when data is absent, e.g. CI); 58 passed)* |
| [x] | 038 | FI-2010: split matrix into LOB (rows 0–39), features (40–143), labels (last 5); label horizons k = 10, 20, 30, 50, 100 | M | 5L-07 | Unit test on shapes and label values ∈ {1, 2, 3} *(done 2026-09-20: `split_matrix()` / `load()` in `research/helios/ml/fi2010.py` return `FI2010Data` with one row per event: `lob` (n, 40), `features` (n, 104), `labels` (n, 5, int8, horizons k = 10, 20, 30, 50, 100 via `labels_for(k)`); rejects labels other than 1 (up) / 2 (flat) / 3 (down) and wrong shapes; 6 new tests incl. real day-10 split; 64 passed. Measured label mix (up/flat/down %) train k=10: 19.7/60.5/19.7, k=100: 40.6/19.4/40.0)* |

**Checkpoint 3:** Postgres running; config and lineage helpers merged; 5 ADRs approved; FI-2010 loads.

---

## Sprint 4 (Week 4): Download and clean bar data

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [x] | 039 | `scripts/download_binance.py`: CLI args `--symbol --interval --start YYYY-MM --end YYYY-MM`; builds monthly URLs | S | 5B-01 | `--dry-run` prints correct URLs *(done 2026-09-20: logic in `research/helios/data/binance.py` (`Month`, `month_range`, `KlineFile` with url / checksum_url / path in the existing `data/binance/spot/klines_<interval>/` layout, `plan_klines`, `--symbol universe` expands configs/universe.yaml), thin CLI `scripts/download_binance.py`; `--dry-run` prints `exists`/`missing` per file; real dry-run: BTC 1h 2017-08→2026-08 = 109 planned, 109 on disk; universe 1m 2024-09→2026-08 = 120 planned, 24 on disk, 96 to download; 17 tests, no network; also fixed `.gitignore` `data/` → `/data/` (it was hiding the new `research/helios/data/` package); 84 passed)* |
| [x] | 040 | Add download with retries; skip file if already present; months that return 404 (before listing) are skipped with a log line | S | 5B-01 | Re-run downloads nothing new *(done 2026-09-20: `fetch_to_file` streams in 1 MB chunks via a `.part` file renamed only when complete (stdlib `urllib`, no new deps); `download_file` skips files already on disk, marks HTTP 404 as `not-found` (no retry), retries network errors / 5xx / 429 with waits 2, 4, 8, 16 s (`--retries`, default 4), never retries other 4xx; `run_downloads` prints `[n/N] status file` + summary, exit 1 if any failed; 9 new tests with a fake network; real check in a temp folder: 2 × BTC 1d downloaded, 2017-01 → not-found, re-run → 2 skipped; 92 passed)* |
| [x] | 041 | Checksum: download `<file>.zip.CHECKSUM`, verify sha256, delete and retry on mismatch | S | 5B-01 | Test with a corrupted file *(done 2026-09-20: `expected_checksum` downloads Binance's `.CHECKSUM` (`<sha256>  <file>`), validates it and keeps a copy as `<file>.zip.CHECKSUM` next to the zip (offline re-checks); `sha256_file` hashes in 1 MB chunks; every download is verified, a mismatch deletes the file and retries; files already on disk are verified too (OK → skipped, damaged → re-downloaded); checksum 404 → not-found; 13 download tests incl. mismatch-then-success, persistent mismatch, damaged file replaced, offline skip; real check: corrupted file was detected and replaced; 98 passed)* |
| [x] | 042 | Verify checksums of the BTCUSDT files already in `data/` | S | 5B-01 | All OK *(done 2026-09-20: ran `scripts/download_binance.py` over the existing files: BTCUSDT 1h 2017-08→2026-08 **109/109 checksum OK**, BTCUSDT 1m 2024-09→2026-08 **24/24 checksum OK**, 0 downloaded, 0 failed; 133 `.CHECKSUM` copies now stored next to the zips (in gitignored `data/`), so future checks are offline)* |
| [x] | 043 | Download **1h** for ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT (full history) | S | 5B-02 | 5 coins of 1h data present *(done 2026-09-20: requested 2017-08→2026-08 for each coin, all files checksum-verified, 0 failed: ETHUSDT 109 (from 2017-08), SOLUSDT 73 (from 2020-08; 36 earlier months not-found), BNBUSDT 106 (from 2017-11; 3 not-found), XRPUSDT 100 (from 2018-05; 9 not-found); not-found months are exactly the months before each listing, no gaps; `klines_1h` now 497 zips + 497 checksums, 20 MB)* |
| [x] | 044 | Check disk (`df -h`), then download **1m** for the 4 other coins, 2024-09 → 2026-08 | S | 5B-03 | 5 × 24 monthly 1m zips *(done 2026-09-20: 27.9 GB free before start; ETH, SOL, BNB, XRP 1m 2024-09→2026-08 downloaded, 24 files each = 96, all checksum-verified, 0 not-found, 0 failed, 5 minutes; `klines_1m` now 5 coins × 24 = 120 zips + 120 checksums, 221 MB)* |
| [x] | 045 | `helios/data/binance.py`: `read_klines(zip_path)` → DataFrame with the 12 named columns | S | 5B-04 | Test with a tiny fixture zip in `research/tests/fixtures/` *(done 2026-09-20: reader put in a new `research/helios/data/klines.py` instead of `binance.py`, which is now ~340 lines of downloading; `read_klines(zip)` reads the CSV straight from the zip into a DataFrame with the 12 named columns and numeric dtypes (`open_time`, `close_time`, `trades` int64, rest float64), raising `KlineFormatError` for a missing file, a bad zip, not exactly 1 CSV, no rows, wrong column count or a header row; values are left exactly as Binance wrote them (step 046 unifies ms/µs). Checked **all 617 zips on disk**: every one has 12 fields and no header row; timestamps are ms up to 2024-12 (417 files) and µs from 2025-01 (200 files). Two committed fixtures built from 3 real rows each: `research/tests/fixtures/BTCUSDT-1h-2024-12.zip` (ms) and `…-2025-01.zip` (µs), 345/346 bytes; 13 tests; added `pandas-stubs` to the dev group so mypy strict passes; 111 passed)* |
| [x] | 046 | `normalise_ts()`: values ≥ 1e14 are µs, else ms → int64 UTC microseconds | S | 5B-05 | Test with one 2024 row (ms) and one 2025 row (µs) *(done 2026-09-20: in `research/helios/data/klines.py`: `normalise_ts(series)` judges each value on its own (`>= 1e14` µs, else ms × 1000) and returns int64 UTC microseconds, refusing non-integer, empty or out-of-range columns (anything outside 2009–2100, so a seconds file fails loudly instead of converting silently); `normalise_klines(frame)` converts `open_time` + `close_time` on a copy; `to_utc()` for readable output. Threshold is safe because 1e14 µs = 1973 but 1e14 ms = year 5138. Real check on 4 months across the boundary (2024-11…2025-02, 2,880 candles): one strictly increasing timeline, every gap exactly 3,600,000,000 µs. 11 new tests incl. a mixed-unit column; note millisecond files close 1 ms before the next candle, microsecond files 1 µs; 122 passed)* |
| [x] | 047 | `validate_bars(df)`: prices > 0, high ≥ max(open, close), low ≤ min(open, close), volume ≥ 0 → returns bad rows (never fixes them) | S | 5B-06 | Test with a broken fixture row *(done 2026-09-20: `validate_bars(frame)` in `research/helios/data/klines.py` returns only the offending rows, unchanged, with a `problems` column naming every rule they break (several can break at once); it never repairs or drops anything. Rules: missing value, price not above zero, high below open or close, low above open or close, high below low, negative volume (base or quote), negative trade count, taker volume above total volume; missing columns raise `KlineFormatError`. Swept **all 617 real files: 5,617,391 candles, 0 bad** — the data is clean, and the rules are proven not to fire on good data. 14 new tests (one per rule, several broken at once, bad rows returned untouched); 136 passed)* |
| [x] | 048 | `find_gaps(df, interval)` + duplicate check on the expected time grid → gaps DataFrame (never fills) | S | 5B-07 | Test: deleted row appears as a gap *(done 2026-09-20: in `research/helios/data/klines.py`: `INTERVAL_US` / `interval_us()`, `find_gaps(frame, interval)` → one row per unbroken run of missing candles (`gap_start`, `gap_end`, `missing`, + readable UTC columns), `find_duplicates()` (returns every copy), `find_off_grid()` (timestamps not on an exact interval boundary). Nothing is ever filled: a missing candle means the exchange was down, and inventing a price would feed made-up data into every later result. `find_gaps` refuses off-grid input instead of guessing. Real sweep of the full history: **1m is perfect** (5 × 1,051,200 candles, 0 gaps, 0 dups); **1h has real outages** — BTC/ETH 170 missing in 28 runs, BNB 163 in 27, XRP 87 in 25, SOL 19 in 10, 0 duplicates anywhere; biggest is the **Feb 2018 Binance outage (75 hours, 2018-02-08 → 02-11)**, which also left **43 off-grid candles in BTC/ETH/BNB 2018-02** starting at e.g. 09:28:14.789 instead of 09:00 (640 of 672 rows). 13 new tests; 149 passed)* |
| [x] | 049 | FI-2010: per-day split exactly like DeepLOB (train days 1–7, test days 8–10), return torch-free numpy arrays | M | 5L-07 | Test on array lengths *(done 2026-09-20: `load_split()` in `research/helios/ml/fi2010.py` returns `FI2010Split(train, val, test)` as plain numpy (no torch): train = first 80 % of the days 1-7 file, val = last 20 % **in time order, never shuffled** (shuffling would let the model see its own future), test = days 8, 9, 10 joined; helpers `concat()` and `take()` with range checks. Real lengths confirmed: **train 203,800 + val 50,950 = 254,750**, test 55,478 + 52,172 + 31,937 = **139,587** events. 10 new tests on fake zips + 1 on the real data; the real one loads the 607 MB file, so it is marked `slow` and left out of the default run (marker registered in `pyproject.toml`, `addopts` now ends with `-m 'not slow'`; run it with `uv run pytest -m slow`); 160 passed + 1 slow)* |
| [x] | 050 | FI-2010 baseline 1: logistic regression on the 40 LOB columns, horizon k = 10, seeds 0/1/2 | M | 5L-08 | Accuracy + macro-F1 per seed saved to a CSV *(done 2026-09-20: `research/helios/ml/baselines.py` (`LogisticBaselineConfig`, `run_logistic_baseline`, `majority_accuracy`) + `scripts/fi2010_baseline.py` -> `reports_out/fi2010_logreg_k10.csv`, one row per seed carrying accuracy, macro-F1, the always-predict-the-commonest-class score, git commit, dirty flag, config hash and timestamp. **Real result (k=10, 203,800 train / 139,587 test): accuracy 0.7069, macro-F1 0.2814, majority 0.7066, ~9 s per fit, identical for seeds 0/1/2** (deterministic solver, so equal numbers prove there is no hidden randomness). Reading: logistic regression on raw order-book levels learns almost nothing - it is barely above always answering 'flat', which is why macro-F1 is the gate, not accuracy. Every later model must beat **macro-F1 0.281**. Added scikit-learn 1.9.1 (+ a narrow mypy exception, since it ships no type information) and dropped its deprecated `n_jobs`; 10 new tests on tiny made-up data; 169 passed)* |

---

## Sprint 5 (Week 5): Parquet, DB schema, registry

| ✓ | Step | What to do | Owner | Plan ID | Done when |
|---|---|---|---|---|---|
| [x] | 051 | `scripts/build_bars.py`: zips → read → normalise → validate → write Parquet `data/processed/bars/source=binance/interval=…/symbol=…/year=…/` | S | 5B-08 | Parquet files appear *(done 2026-09-20: `research/helios/data/bars.py` (`monthly_zips`, `load_history`, `build_bars`, `write_bars`, `read_bars`, `BuildResult`) + CLI `scripts/build_bars.py --symbol universe --interval 1h`. Flow: zips -> read -> one time unit -> validate + gap and off-grid checks -> drop duplicate timestamps -> sort -> one zstd Parquet per year at `data/processed/bars/source=binance/interval=../symbol=../year=../bars.parquet` (the useless `ignore` column is dropped). Nothing is repaired: bad rows, gaps and off-grid rows are only reported, and off-grid bars are still written because they are real trades. **Real build: 61 Parquet files, 285 MB, 5,617,391 bars, 0 bad rows, 0 duplicates** (1h 14 s, 1m 28 s); reading a whole year of minute bars back takes **0.44 s** instead of unzipping and parsing. 12 new tests built from the two committed fixtures; 181 passed)* |
| [x] | 052 | Also write `data/processed/reports/{validation,gaps}_<symbol>_<interval>.parquet` | S | 5B-07 | Reports exist *(done 2026-09-20: `validation_report()`, `gap_report()`, `write_reports()` and `read_report()` in `research/helios/data/bars.py`; `scripts/build_bars.py` now also writes `data/processed/reports/{validation,gaps}_<symbol>_<interval>.parquet` (`--report-dir`). The validation report carries symbol, interval, open_time, readable UTC time and the problems, and includes off-grid timestamps as their own problem; the gap report has one line per unbroken run of missing bars. Reports are written **even when clean**, because a file that says 'nothing wrong' is evidence while a missing file only means nobody looked. **Real run: 20 report files.** BTC/ETH/BNB 1h each record 43 off-grid candles (the 2018-02-09 09:28:14.789 restart) and 28/28/27 gap runs (170/170/163 missing hours, biggest the 75-hour outage 2018-02-08 01:00 -> 02-11 03:00); SOL 19 missing, XRP 87; every 1m report is empty. 7 new tests; 188 passed)* |
| [x] | 053 | Run `build_bars.py` for 5 coins × 1h and 5 coins × 1m; read the gap report | S | 5B-08 | Gap counts noted in `docs/research/data_quality.md` *(done 2026-09-20: bars + reports built for all 10 combinations (5 coins x 1h, 1m) and `docs/research/data_quality.md` written by the new `scripts/data_quality_report.py`, which reads `data/processed/reports/` so **no number is typed by hand** - re-running after a rebuild refreshes the document and `git diff` shows what changed in the data. It records the generating commit and whether the tree was dirty. Hourly: BTC/ETH 79,117 bars (170 missing, 28 runs, 43 off-grid), BNB 77,181 (163, 27, 43), XRP 72,913 (87, 25), SOL 53,063 (19, 10); worst gap 75 bars from 2018-02-08 01:00; minute: 1,051,200 bars per coin with nothing missing; 0 bad rows anywhere. The document also states the consequences: gaps mean 'unknown' not 'no change', and features must read timestamps rather than row positions because of the Feb 2018 off-grid bars; 188 passed)* |
| [x] | 054 | `helios/data/loader.py`: `load_bars(symbols, interval, start, end)` using DuckDB over Parquet | S | 5B-10 | Test on time filter; 9 years × 5 coins hourly loads in < 5 s *(done 2026-09-20: `research/helios/data/loader.py`: `load_bars(symbols, interval, start, end, out_dir)` queries the Parquet store with DuckDB and `hive_partitioning`, filtering on the `year=` folder as well as the timestamp so whole files are skipped; also `to_micros()` and `available_symbols()`. Accepts one coin or a list, and dates as 'YYYY-MM-DD', `date`, `datetime` (naive means UTC) or raw microseconds; **start and end are inclusive UTC**. **Speed on the real store: all 9 years x 5 coins hourly = 361,391 bars in 1.85 s** (target < 5 s), one year 0.94 s, one month 0.85 s, a full year of minute bars (525,600) in 2.37 s. A test caught a real bug: an end date written as text was treated as midnight, so the last day was cut off (June returned 697 bars instead of 720, a minute year 524,161 instead of 525,600); a date-only string now behaves like a `date`. 19 new tests; 207 passed)* |
| [x] | 055 | Sanity test: resample BTC 1m → 1h and compare with downloaded 1h over the overlap | S | 5B-11 | Mismatch count printed; should be ~0 *(done 2026-09-20: `research/helios/data/resample.py` (`resample_bars`, `compare_bars`, `compared_count`) + `scripts/check_resample.py`. One rebuilt bar = first open, highest high, lowest low, last close, summed volumes/trades, and an hour is only produced when **all 60 minutes are present** (a missing minute could hide the real high or low). Comparison allows a 1e-9 relative difference on sums, since adding 60 numbers can differ in the last bits. **Real cross-check over the 2-year overlap: all 5 coins, 1,051,200 minute bars each -> 17,520 complete hours, 17,520 hours compared, 0 mismatching values.** The minute and hourly files are separate downloads, so this is independent evidence that the downloads, the ms/us handling and the Parquet build are all correct. It also caught a loader bug: a timestamp taken straight from a column is a numpy integer, which Python does not count as an `int`, so it was misread as a date - `to_micros` now accepts numpy integers. 15 resample tests + 2 loader tests; 224 passed)* |
| [x] | 056 | `uv run alembic init`; `env.py` reads DB URL from `.env` | S | 5C-01 | `alembic upgrade head` runs *(done 2026-09-20: `uv run alembic init research/migrations` -> `alembic.ini` at the root + `research/migrations/{env.py,script.py.mako,versions/}`. **No connection string is committed**: the generated `sqlalchemy.url = driver://user:pass@...` line was removed and `env.py` builds the URL from `helios.common.db.get_settings()`, i.e. the POSTGRES_* variables in `.env`. Migration files are dated (`file_template`) and timestamped in UTC; `target_metadata = None` because tables are written by hand and read in review, not autogenerated. Verified: offline mode (`alembic upgrade head --sql`) runs without a database and the password appears **0 times** in its output; with Postgres up, `alembic upgrade head` succeeded and created the `alembic_version` table (`alembic current` clean). Docker Desktop was restarted for this; both containers are healthy, so the database test runs again: **232 passed**. Also added `infra/README.md` after hitting a real trap: `docker compose -f infra/docker-compose.yml up -d` fails with 'required variable POSTGRES_USER is missing' because Compose looks for `infra/.env`; the correct command is `docker compose --env-file .env -f infra/docker-compose.yml up -d`. 7 new tests guard that no URL or password reaches a committed file)* |
| [x] | 057 | Migration 001: `instruments`, `data_snapshots`, `experiments` | S | 5C-02 | Tables visible in Adminer *(done 2026-09-20: migration `research/migrations/versions/20260920_8fcab6513ac4_001.py` creates **instruments** (symbol unique and upper-case, venue, base/quote asset, tick_size and lot_size as exact NUMERIC(38,18) and > 0, first_available_date for `universe_on()`, active, created_at), **data_snapshots** (snapshot_id = sha256 over the sorted file list, source, interval, symbols jsonb, first/last open_time in UTC microseconds, file_count, row_count, total_bytes, code_commit, with checks that the range is ordered and the file and row counts are positive) and **experiments** (kind and status limited to known values, a hypothesis of at least 10 characters written **before** the run, author, pre_registered_at, code_commit, config_hash, optional snapshot_id with `ON DELETE RESTRICT` so the data behind a result cannot vanish). Verified `upgrade head` -> 3 tables, `downgrade base` -> clean, `upgrade head` again -> 3 tables, so the migration works both ways. 16 new tests in `research/tests/test_schema.py` run against the real PostgreSQL inside a rolled-back transaction (they skip when no database is reachable) and prove the database itself refuses a lower-case symbol, a zero or negative tick size, a duplicate symbol, a backwards date range, an unknown experiment kind or status, a too-short hypothesis, a missing snapshot reference and the deletion of a snapshot still in use; a NUMERIC price also comes back exactly. 248 passed)* |
| [x] | 058 | Seed `instruments` from `universe.yaml` (symbol, tick size, lot size, first available date) | S | 5B-12 | 5 rows *(done 2026-09-20: `research/helios/data/instruments.py` + `scripts/seed_instruments.py` (`--dry-run` shows the table first). Nothing is typed by hand: the coin list comes from `configs/universe.yaml`, tick and lot sizes from Binance's exchange-information API (`PRICE_FILTER.tickSize`, `LOT_SIZE.stepSize`, read as exact `Decimal`), and `first_available_date` from the earliest bar in our own Parquet store via the new `loader.first_open_time()` (only the timestamp column is read). `status != TRADING` sets `active = false`. Writing is an upsert on the symbol, so re-running is safe: ran it twice, still 5 rows. **5 rows written** - BTCUSDT tick 0.01 / lot 0.00001 from 2017-08-17, ETHUSDT 0.01 / 0.0001 from 2017-08-17, BNBUSDT 0.01 / 0.001 from 2017-11-06, XRPUSDT 0.0001 / 0.1 from 2018-05-04, SOLUSDT 0.01 / 0.001 from 2020-08-11. 17 new tests (Binance's answer replaced by a fixed example, database tests inside a rolled-back transaction); 263 passed)* |
| [x] | 059 | `register_snapshot()`: file list + sha256 + date range → `data_snapshots` row; called at end of `build_bars.py` | S | 5B-09 | Snapshot ids stored *(done 2026-09-20: `research/helios/data/snapshots.py` (`SnapshotFile`, `Snapshot`, `compute_snapshot_id`, `describe_bars`, `write_manifest`, `load_manifest`, `register_snapshot`), called at the end of `scripts/build_bars.py` (`--snapshot-dir`, `--no-snapshot`). The id is `sha256` over the sorted lines `<relative path>  <file sha256>`, so it is **deterministic** (same files -> same id on any machine, paths are relative) and **sensitive** (one changed byte -> completely different id). The row goes to `data_snapshots` with `ON CONFLICT DO NOTHING`, because a snapshot is never updated; the full file list is written to `data/processed/snapshots/<id>.json`, since the summary alone cannot say *which* file changed. A database that is not running only warns - the build still succeeds. **Real snapshots stored: hourly `9d75c8de86a8...` (46 files, 361,391 rows, 2017-08-17 -> 2026-08-31, 26 MB) and minute `b1799dbee6c6...` (15 files, 5,256,000 rows, 2024-09-01 -> 2026-08-31, 272 MB); rebuilding gave the same ids and 'already in data_snapshots'.** 20 new tests. Seeding real coins in step 058 also exposed 5 older tests that assumed empty tables - they now use fake symbols (`TESTAUSDT`...) and relative counts, and the snapshot test edits a Parquet file **validly** instead of appending a byte; 282 passed)* |
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
