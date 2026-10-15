# Local verification for steps 155–160

The retained quantitative and ML research and public PAPER observations are
documented separately with their exact clean source commits and hashes. No
research attempt or public session was rerun to improve an outcome. Original
22 results/12 definitions and 71 feature files are unchanged; TEST access is zero.

The final broad local run reported **1,744 passed**, one slow test deselected and
15 existing warnings. Its remaining failure was a backtest test that assumed
the checkout must be dirty; this run began clean. That fixture now explicitly
tests both clean and dirty lineage and compares persisted flags and commits
with the saved artifact. The affected backtest, dashboard and PostgreSQL schema
groups subsequently passed **38 tests**. The earlier three-second Streamlit test
timeout and migration-007 head expectation were also corrected and verified.
PAPER execution and research code did not change after the verified public session.

Final Ruff lint/format checks passed for 264 files, strict mypy passed for 103
package sources, and `uv lock --check` passed. The local full-run logs and final
targeted verification are retained outside Git. GitHub CI is checked against
the exact final pushed commit in addition to these local checks.

The first pushed CI run caught a Streamlit/spawn interaction: AppTest can leave
the page as the process entrypoint, causing spawned workers to execute its
top-level UI/database code. The page now renders only through guarded `main()`;
report/error branches return explicitly. Regression tests cover both inert
`__mp_main__` reimport and an actual spawned worker with the page entrypoint and
deliberately invalid database settings. Research artifacts are not reevaluated
for this dashboard-only correction.

The public session is a bounded integration demonstration with one simulated
fill. It establishes neither a promoted alpha nor a 24-hour live soak.
