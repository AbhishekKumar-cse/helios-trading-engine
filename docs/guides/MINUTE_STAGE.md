# Minute stage profile (153)

`configs/stages/minute.yaml` binds H-MINUTE, interval `1m`, feature set v1,
525,600 periods per year, accepted UTC splits and the unchanged `gates_v1`
thresholds. Load it with `helios.common.project_config.load_minute_stage()`.
The validated resolved profile has a stable configuration hash for later runs.

TRAIN is 2024-09-01–2025-08-31, VALID 2025-09-02–2026-02-28 and TEST
2026-03-02–2026-08-31, inclusive UTC dates. Both embargoes are one full day.
The typed loader compares the profile with the authoritative split/gate files;
hourly annualization, cross-family intervals, changed dates or relaxed thresholds
are refused. Changes to accepted policy still require a new ADR and version.

G1–G6 apply within this family. Sharpe/Fitness use 525,600 periods per year;
turnover is mean absolute position change **per minute**. Cross-family comparison
uses the existing daily-aggregated Sharpe convention, with fewer than 30 observed
days reported as N/A. Fees/slippage remain the accepted `configs/fees.yaml`.

The profile loads policy metadata only. It does not authorize TEST observations,
register an alpha, fit a model, evaluate gates or adapt the hourly-only evaluation
CLI to minute execution. Those later research tasks retain preregistration,
availability, embargo and guarded TEST requirements. Minute feature exports from
step 152 are already available; no feature rebuild is required here.
