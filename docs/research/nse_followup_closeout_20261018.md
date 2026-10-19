# NSE minute breadth and PAPER safety follow-up

Source assessment completed with **NOT CERTIFIED**; promotion remains blocked.
The retained public data does not prove exact original minute share/volume units,
causal availability or executable liquidity. See the per-company certification record.

Preregistered round `nse_minute_breadth1` executes minute baselines on AXISBANK, TCS, SUNPHARMA. All inputs, fees and gates remain fixed.
Source `6ce3a0b838a97055a5f4fca80c148a8e3a29309b`; evaluator dirty=True.
Protocol dirty=False; summary dirty=False.
Git markers are preserved independently; evaluator results are never relabelled clean.
Later PAPER safety edits do not alter the frozen research runtime.

| Company | Candidate | Status | VALID daily Sharpe |
|---|---|---|---:|
| AXISBANK | momentum | REJECTED | -186.083365 |
| SUNPHARMA | momentum | REJECTED | -165.037647 |
| TCS | momentum | REJECTED | -165.453079 |
| AXISBANK | reversal | REJECTED | -275.359999 |
| SUNPHARMA | reversal | REJECTED | -282.069065 |
| TCS | reversal | REJECTED | -295.533710 |
| AXISBANK | ml | INVALID | unavailable |
| SUNPHARMA | ml | INVALID | unavailable |
| TCS | ml | INVALID | unavailable |

Independent checks reconcile 132,206 base fills and 684 candidate/session replays, including
reference tax settlements, cash, coverage, metrics, gates and registry outcomes.
Results describe independent fixed-capital sessions, not a compounded account.
No eligible alpha, TEST access, promotion or crypto-result change occurred.

PAPER changes: equity-aware atomic dashboard kill; fresh-close startup; feed-silence
halt/cancellation; exclusive PostgreSQL ownership with connection-loss detection;
crash recovery that reconstructs durable fills and every accounting checkpoint,
cancels dead simulated intents, retains open inventory and closes the scope halted.
Recovery never resumes trading or invents an exit fill.

Verification: **1850 tests passed**, 1 slow test deselected,
15 existing warnings; Ruff/format and strict mypy pass. Synthetic
observations and rolled-back real PostgreSQL; they establish software behavior only.

Actual preflight: normal NSE session closed on Sunday2026-10-18; new working-tree
changes are uncommitted. Preflight collected zero observations or fills.
A clean-source open-session run must measure public-feed freshness, operator kill and
actual process-stop/recovery. Trials and the same-date comparison remain open.
See `docs/guides/NSE_PAPER_RECOVERY.md` for run/recovery commands and limits.

Acceptance requirements remain unresolved; fifth semester is incomplete.
