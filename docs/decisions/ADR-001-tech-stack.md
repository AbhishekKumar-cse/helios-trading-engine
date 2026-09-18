# ADR-001: Technology stack and architecture

| | |
|---|---|
| **Status** | Accepted (2026-09-18) |
| **Date** | 2026-09-18 |
| **Deciders** | Abhishek Kumar (team lead) |
| **Plan task** | 5A-12 (step 031) |
| **Replaces** | none |

## Context

The HELIOS specification (`docs/spec/HELIOS_SRS_and_System_Design_v1.md`) left several
technology questions open, and two source documents disagreed:

- **Conflict C-1 / OPEN-01:** the earlier synopsis used Go/Rust for the matching engine and
  trading services; the updated knowledge base says C++ for the latency-sensitive path.
- **OPEN-02:** where the market data comes from (paid LOBSTER data was out of budget).
- **OPEN-03:** which time horizon the alphas target.
- **OPEN-08:** which event-log technology to use.

A team of three part-time students must be able to build and run everything on laptops and
free services, over three semesters, with results that can be reproduced.

## Decision

`ARCHITECTURE_AND_TECH_STACK.md` (version 1.0, 2026-09-12) is the project's fixed technical
reference. Its main points:

| Area | Decision |
|---|---|
| Priorities | 1. Alpha / quant research · 2. Fault tolerance · 3. Low latency |
| Languages (OPEN-01) | **Python 3.12** for research, data, backtests and ML · **C++20** for the matching engine (6th sem) and the latency hot path (7th sem) · **Go** for the replication cluster (7th sem) · **TLA+** for the protocol spec. No other runtimes without a new ADR |
| Python is the reference | Anything ported to C++ must pass a parity test against the Python version |
| Data (OPEN-02) | Free crypto data first (Binance klines/trades, Bybit L2 order book); FI-2010 for the ML benchmark |
| Horizon (OPEN-03) | Stepwise: **hourly → minute → second → millisecond** |
| Event log (OPEN-08) | Redpanda (7th sem) |
| Storage | PostgreSQL 16 (+ pgvector later) for registry, orders, fills, audit; Parquet + DuckDB for market data |
| Tooling | uv, pytest + hypothesis, ruff, mypy strict, pre-commit + gitleaks, GitHub Actions CI |
| Runtime | Docker Compose now, k3s (lightweight Kubernetes) in the 7th semester; development on WSL2 Ubuntu 24.04 |
| Execution | Simulated only (`is_simulated = true`); one `ExecutionVenue` interface for the paper venue and, later, the matching-engine cluster |
| Research integrity | No invented numbers; every result carries commit, config hash, data snapshot and seed |

Still open, each with its own later task: OPEN-04 Fitness formula (ADR-002, step 032),
OPEN-05 fill model, OPEN-06 engine benchmark flow, OPEN-07 DGT online/offline,
OPEN-09 kernel bypass.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| **A: Python research + C++ hot path + Go cluster (chosen)** | Fast research iteration; C++ where speed is measured; Go is simpler for networking and concurrency | Three languages to maintain | — |
| B: Everything in C++ | One fast language | Very slow research iteration; weak ML ecosystem | Priority 1 is finding alphas, not speed |
| C: Everything in Python | Simplest | Cannot meet the latency goals; garbage-collection pauses | Priority 3 would be impossible |
| D: Rust instead of C++ / Go | Memory safety | Team has less experience; smaller quant ecosystem | Higher risk for a student timeline |
| E: Paid LOBSTER data | Standard academic LOB data | Cost | Free crypto data covers every horizon stage |

## Consequences

- **Good:** research starts immediately in Python; the same Python code later becomes the
  correctness reference for C++; everything runs on free tools and data.
- **Bad / costs:** three languages by the 7th semester; crypto trades 24/7 and has maker/taker
  fees, so Sharpe annualisation and cost models differ from equity papers; the Bybit L2 book
  has no order IDs, so queue position is estimated.
- **Follow-up work:** ADR-002 to ADR-005 (steps 032–035) settle Fitness, horizons, split dates
  and fees; the parity test (7th sem) enforces Python = C++.
- **How we will know it was wrong:** if Python research becomes too slow for minute-level
  work, or if the team cannot sustain three languages, revisit with a new ADR.

## References

- `ARCHITECTURE_AND_TECH_STACK.md` §1–§11 (version 1.0, 2026-09-12)
- `docs/spec/HELIOS_SRS_and_System_Design_v1.md`: conflict C-1, open decisions OPEN-01 to OPEN-10
- `5thSem/5thSem_Plan.md`, `6thSem/6thSem_Plan.md`, `7thSem/7thSem_Plan.md`
