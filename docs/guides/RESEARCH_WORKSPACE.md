# HELIOS research workspace

The existing local Streamlit app now separates building, data exploration, retained
results and PAPER monitoring. Start it with the command in
[REGISTRY_DASHBOARD.md](REGISTRY_DASHBOARD.md) and open http://localhost:8501.

| Navigation | Purpose |
| --- | --- |
| Build & simulate | Configure one of three existing templates, run the shared synthetic backend, inspect equity/trades/risk and replay the result. |
| NSE research | Review downloaded equity data and retained strategy experiments. The rebuilt collection separates strategy results, price observations and data-quality evidence. |
| Datasets & fields | Search HELIOS's declared field contracts, units, shapes and availability rules. A contract is not proof of collected coverage. |
| Saved results | Search the registry and open checksum-verified reports. Missing metrics remain unavailable. |
| Paper monitor | View actual retained simulated-session checkpoints and the existing audited halt control. |

The template signal preview is descriptive notation, not an arbitrary-code editor.
Changes to settings leave the displayed run unchanged until **Run simulation** is
pressed; a visible notice identifies unapplied settings. Replay reveals only the
observations and fills available at its cursor. Generated-price results are labelled
synthetic and do not establish an eligible alpha.

The existing `?page=equities`, `?page=registry`, `?page=paper` and `?run=<UUID>`
links continue to work. Navigation clears an old report when leaving the registry;
new URLs override a previous sidebar selection. No research evaluation, promotion,
TEST access, external deployment or real-order control was added.

Formula-only retained rounds render without an ML calibration file. If a round does
claim model calibration, its existing evidence checks still apply and fail visibly.
The original report integrity, withheld-price filters, P&L accounting and PAPER
kill/audit code paths remain in use.

Workflow references consulted: [QuantConnect backtesting results](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results)
and [WorldQuant BRAIN](https://www.worldquant.com/brain/). This is HELIOS's own
interface over its existing backend, not an implementation of proprietary platform features.

Verification: 21 existing dashboard tests passed, including the database-backed
PAPER halt/audit flow; three new regressions cover route synchronization, field
search/empty state and formula-only research display. The final simulation subset
also passed after moving the run button. Scoped Ruff and strict typing passed.
