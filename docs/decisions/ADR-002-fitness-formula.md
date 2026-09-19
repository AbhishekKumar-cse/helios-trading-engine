# ADR-002: Fitness formula (gate G2)

| | |
|---|---|
| **Status** | Accepted (2026-09-19, floor 0.125 approved by team lead) |
| **Date** | 2026-09-19 |
| **Deciders** | Abhishek Kumar (team lead) |
| **Plan task** | 5A-12 (step 032) |
| **Replaces** | none |

## Context

Gate **G2** says an alpha must have **Fitness > 1** before it can be promoted, but the
knowledge base never defines Fitness (open decision **OPEN-04**, audit item **A-31**).
An undefined gate is not a gate: two people would compute it differently and both believe
they follow the spec. The formula, including every constant, must be fixed **before the
first alpha is evaluated** (steps 102 and 108 implement it).

Fitness exists to punish alphas that need a lot of trading to earn their Sharpe: every
trade costs fees, so a high-turnover alpha is fragile even if its Sharpe looks good.

## Decision

```
Fitness = Sharpe × sqrt( |annual_return| / max(turnover, floor) )

floor = 0.125
```

| Term | Exact meaning (same numbers the other gates use) |
|---|---|
| `Sharpe` | Annualised Sharpe ratio of the alpha's P&L **net of trading costs** (risk-free rate = 0), computed per decision period of the alpha's horizon family and annualised with that family's `periods_per_year` (ADR-003) |
| `annual_return` | Mean net P&L per period × `periods_per_year`, as a fraction (0.12 = 12 % per year) |
| `turnover` | Mean of \|position(t) − position(t−1)\| per decision period, as a fraction (0.30 = 30 %), the same value tested by gate G3 |
| `floor` | 0.125. The smallest turnover the formula will divide by |
| `|…|` | Absolute value. The sign comes from Sharpe, so a losing alpha always has negative Fitness |

- The formula and `floor` are stored in `configs/gates_v1.yaml` (step 036). Every
  alpha result records the config hash (step 027), so it is always known which formula was used.
- Following the spec's recommendation, every result **also reports `cost_stress_sharpe`**
  (Sharpe at 2× the assumed cost), which gate G6 already checks.

## Worked examples

| Alpha | Sharpe | annual_return | turnover | max(turnover, 0.125) | Fitness | G2 (> 1) |
|---|---|---|---|---|---|---|
| A: busy trader | 1.5 | 0.12 | 0.30 | 0.30 | 1.5 × √(0.12 / 0.30) = 1.5 × 0.632 = **0.949** | Fail |
| B: calm trader | 1.2 | 0.20 | 0.15 | 0.15 | 1.2 × √(0.20 / 0.15) = 1.2 × 1.155 = **1.386** | Pass |
| C: barely trades | 1.5 | 0.12 | 0.05 | **0.125** | 1.5 × √(0.12 / 0.125) = 1.5 × 0.980 = **1.470** | Pass |
| D: loser | −0.8 | −0.10 | 0.20 | 0.20 | −0.8 × √(0.10 / 0.20) = **−0.566** | Fail |

Alpha A has a good Sharpe, but it trades so much that Fitness rejects it, which is the point
of the gate. For alpha C **without** a floor, Fitness would be
1.5 × √(0.12 / 0.05) = **2.324**: an alpha that hardly trades would look far better than
it is, and in the limit (turnover → 0) Fitness would explode. The floor caps that reward.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| **A: floor = 0.125 (chosen)** | Same constant as the common industry alpha-research convention, so results are comparable; strong protection against near-zero turnover | Convention, not law; any alpha with turnover below 12.5 % is treated as if it traded 12.5 % | — |
| B: floor = 0.01 (equal to G3's 1 % minimum) | Matches our own turnover gate | Below 12.5 % turnover Fitness still grows fast (alpha C → 2.32) | Too weak against low-turnover inflation |
| C: no floor | Simplest | Division by ~0 for near-constant alphas | Degenerate, spec rejects it (Opt-2) |
| D: Fitness = Sharpe at 3× cost (spec Opt-3) | Directly measures cost robustness | Non-standard; not comparable to other work | Kept as an extra report (`cost_stress_sharpe`), not as G2 |

## Consequences

- **Good:** G2 becomes a real, automatic gate; results are comparable with the usual
  alpha-research convention; low-turnover alphas cannot game Fitness.
- **Bad / costs:** the 0.125 constant was designed for daily equity alphas; for hourly and
  minute crypto alphas it is a convention we adopt, not a proven optimum.
- **Follow-up work:** add `fitness_turnover_floor: 0.125` to `configs/gates_v1.yaml`
  (step 036); implement in step 102 with a test that reproduces the four examples above.
- **How we will know it was wrong:** if many alphas that pass G1 and G3 fail G2 only
  because of the floor, or pass G2 but collapse in backtest, revisit with a new ADR.

## References

- `docs/spec/HELIOS_SRS_and_System_Design_v1.md`: §19.4 (Fitness options), OPEN-04, audit A-31
- `docs/spec/HELIOS_Updated_Knowledge_Base.pdf`: gates Sharpe > 1, Fitness > 1, 1 % < Turnover < 70 %
