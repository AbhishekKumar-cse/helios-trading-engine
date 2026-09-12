# HELIOS Team Guide

How the three of us work together on HELIOS. Read this once; follow it every day.
Plan references: [5thSem_Plan.md](../5thSem/5thSem_Plan.md) · [5thSem_Sequential_Steps.md](../5thSem/5thSem_Sequential_Steps.md) · [ARCHITECTURE_AND_TECH_STACK.md](../ARCHITECTURE_AND_TECH_STACK.md)

---

## 1. Team and roles

| Name | Roll no. | Role |
|---|---|---|
| **Abhishek Kumar** | BTECH/25002/24 | **Q (Quant researcher), fixed owner.** Also takes S / M steps |
| **Anuj Sharma** | BTECH/25011/24 | S (Systems) and M (ML), shared |
| **Indra Shikari** | BTECH/25028/24 | S (Systems) and M (ML), shared |

**Faculty mentor:** Dr. Shripal Vijayvargiya

| Role | Meaning | Assigned how |
|---|---|---|
| **Q**: Quant researcher | Features, alpha DSL, simulator, gates, research rounds, research notes | Always **Abhishek** |
| **S**: Systems engineer | Repo, data pipeline, database, registry, backtester, risk, OMS, paper venue, live trading | **Shared by all three.** Names chosen every Monday |
| **M**: ML engineer | FI-2010, DeepLOB, ML datasets/models, ML alphas, dashboard | **Shared by all three.** Names chosen every Monday |

---

## 2. Module owners (5th semester)

Every module has exactly one owner **for the current week** (NFR-040). Write the name next to the step in the step file at the Monday meeting.

| Module | What it is | Role | Owner |
|---|---|---|---|
| 5A | Setup, config, lineage, ADRs | S (decisions: Q) | ADRs: Abhishek · rest: weekly pick |
| 5B | Data download + cleaning | S | weekly pick |
| 5C | Database + alpha registry | S | weekly pick |
| 5D | Feature engine | Q | Abhishek |
| 5E | Alpha DSL | Q | Abhishek |
| 5F | Simulator, metrics, gates, leakage suite | Q | Abhishek |
| 5G | Hourly research round | Q | Abhishek |
| 5H | Backtester, strategy, risk, OMS, paper venue | S | weekly pick |
| 5I | Minute research round | Q (+ M) | Abhishek (+ weekly pick) |
| 5J | Live paper trading + dashboard | S + M | weekly pick |
| 5K | Semester close | All | everyone |
| 5L | ML route + FI-2010 + DeepLOB | M | weekly pick |

**Rule for shared S/M work:** steps that must happen in order (for example data → database → registry) stay with **one person for the week**, so nobody waits on someone else. Abhishek carries all Q work, so give him the lighter S/M steps.

---

## 3. Where and how to work

| Rule | Details |
|---|---|
| **Linux only** | Work inside **WSL Ubuntu 24.04** (terminal) or **VS Code window showing "WSL: Ubuntu"** |
| **Commit only from Ubuntu / VS Code WSL** | The pre-commit hooks are installed in Ubuntu. Commits from Windows PowerShell or Git Bash fail with "`pre-commit` not found" |
| **One project folder per laptop** | Abhishek's laptop: `C:\Users\bit\OneDrive\Desktop\helios` (Ubuntu path `/mnt/c/Users/bit/OneDrive/Desktop/helios`). Others: any single folder, never two copies |
| **Virtual environment outside synced folders** | Put `export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/helios"` in `~/.bashrc` and `~/.profile`, so OneDrive or Google Drive never syncs thousands of library files |
| **Same tool versions** | Always install with `uv sync` (reads `uv.lock`). Add libraries only with `uv add <name>` and commit the updated `uv.lock` |
| **Docker** | Open Docker Desktop before using `docker` (it does not start with Windows) |

---

## 4. Branches

- `main` is protected: **no direct pushes**, everything goes through a pull request.
- Branch name = **plan task ID + short description**, lowercase, hyphens:

```
5B-05-timestamps
5F-11-noise-alpha-test
5H-06-risk-price-band
```

- One branch = one step (or a few tightly related steps). Keep branches small, 1–3 days of work.
- Delete the branch after it is merged.

---

## 5. Commit messages

Start with the **plan task ID**, then a short description in plain English:

```
5B-05: normalise ms/µs Binance timestamps
5C-04: block UPDATE/DELETE on alpha_results
5F-11: add noise-alpha calibration test
```

- Present tense, under ~72 characters for the first line.
- Add a blank line and bullet points if more explanation is needed.
- The hooks run on every commit (file fixers, ruff, large-file check, gitleaks). If a hook **fixes** a file, the commit stops. Run `git add -A` and commit again.

---

## 6. Pull request (PR) rules

A PR can be merged only when **all** are true:

1. ✅ **CI is green** ("lint, types, tests": ruff, ruff format, mypy strict, pytest)
2. ✅ **At least 1 review** from a teammate who **did not write** the code
3. ✅ The PR title starts with the plan task ID, e.g. `5B-05: normalise timestamps`
4. ✅ New code has **at least one test**
5. ✅ No data files, no secrets, no files over 1 MB (hooks + `.gitignore` enforce this)
6. ✅ The step's **"Done when"** condition from the step file is met, and the box is ticked in the same PR

**Reviewer checklist:** Does it do what the step says? Is there a test? Any look-ahead / future data used? Any hard-coded numbers that belong in `configs/`? Any result numbers typed by hand?

---

## 7. Never commit

| Never | Why |
|---|---|
| `data/` (market data, Parquet, zips) | Large and re-downloadable. Ignored by git |
| `.env`, passwords, API keys, tokens | Security. gitleaks blocks them |
| `.venv`, caches (`.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `__pycache__`) | Recreated automatically |
| Model checkpoints (`*.pt`, `*.ckpt`), `reports_out/` | Large generated files |
| **Results typed by hand** | Every number must come from a run with lineage (commit, config hash, data snapshot, seed) |

---

## 8. Weekly routine

| When | Duration | What |
|---|---|---|
| **Monday** | 30 min | Pick this week's steps from the step file, **write a name next to every S/M step**, check blockers |
| During the week | — | One branch per step → PR → review → merge. Ask early if stuck for more than half a day |
| **Friday** | 30 min | Each person shows what was **merged** (not just "worked on"). Tick boxes. Move unfinished steps to next week, **keeping the order** |

---

## 9. Research integrity (from the project rules)

- **No invented results.** Numbers come only from executed runs; unmeasured values stay `TBD-MEASURE`.
- **Gates are selection criteria, not promises** (Sharpe > 1, Fitness > 1, 1% < Turnover < 70%).
- **Keep every alpha**, including rejected ones. The test split is touched **at most twice**.
- **Paper / simulated execution only.** No live trading, no colocation or FPGA claims.
- **Report negative results** with the same prominence as positive ones.

---

## 10. New laptop setup checklist

Each teammate does this once on their own laptop (details: steps 001–019 in the step file).

- [ ] ≥ 35 GB free disk space
- [ ] WSL2 + Ubuntu 24.04, then `sudo apt install -y build-essential git curl unzip`
- [ ] uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and `uv python install 3.12`
- [ ] `git config --global user.name` / `user.email` + SSH key added to GitHub
- [ ] Docker Desktop with **WSL integration ON for Ubuntu**, `docker run hello-world` works
- [ ] VS Code + extensions WSL, Python, Ruff, Docker (installed on the WSL side too)
- [ ] Accept the GitHub collaborator invite, clone the repo into **one** folder
- [ ] `export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/helios"` in `~/.bashrc` and `~/.profile`
- [ ] `uv sync`, then `uv run pytest` → passes
- [ ] Install gitleaks v8.30.1 (official release binary, checksum verified) into `~/.local/bin`
- [ ] `uv run pre-commit install`
