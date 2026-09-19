# Architecture Decision Records (ADRs)

An **ADR** is a short document that records one important decision: what we decided,
why, which alternatives we rejected, and what it costs us. Together they are the project's
memory, so nobody has to guess later why something is the way it is.

**Rules**

- One decision per ADR. Start from [`ADR-000-template.md`](ADR-000-template.md).
- File name: `ADR-NNN-short-title.md` (next free number).
- An ADR is **Proposed** until the team lead (Abhishek Kumar) approves it, then **Accepted**.
- Accepted ADRs are never rewritten. To change a decision, write a new ADR that
  supersedes the old one.
- Any change to `ARCHITECTURE_AND_TECH_STACK.md` needs an ADR.

## Index

| ADR | Title | Status | Date |
|---|---|---|---|
| [000](ADR-000-template.md) | Template | — | 2026-09-18 |
| [001](ADR-001-tech-stack.md) | Technology stack and architecture | Accepted | 2026-09-18 |
| [002](ADR-002-fitness-formula.md) | Fitness formula (gate G2), floor 0.125 | Accepted | 2026-09-19 |
| [003](ADR-003-horizon-families.md) | Horizon families and daily-aggregated Sharpe | Accepted | 2026-09-20 |
| [004](ADR-004-split-dates.md) | Train / validation / test split dates | Accepted | 2026-09-20 |
| [005](ADR-005-fees-and-slippage.md) | Trading fees and slippage assumptions | Accepted | 2026-09-20 |
