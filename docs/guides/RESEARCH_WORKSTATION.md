# Research workstation

Open [HELIOS](http://localhost:8501/?page=dashboard). The existing Streamlit
application now uses the compact dark workstation layout reviewed in Alpha
Harness. HELIOS continues to run its own retained-data evaluator and simulated
execution stack. It does not consume BRAIN datasets, quotas or credentials.

## Research flow

1. **Data Explorer:** filter market, family and frequency; search actual retained
   field schemas. Select an executable screened NSE minute/hourly collection and
   use **Bind observed field → Use in Template Lab**. Other collections expose
   metadata and their restrictions without implying executable support.
2. **Template Lab:** choose up to three companies, edit a causal DSL template,
   bind `$field` and finite comma-separated `$lookback` values, and write the
   hypothesis. Lookbacks count completed bars within one session: 1–60 minute
   bars or 1–4 hourly bars. These are not trading-day windows. Missing data and
   warmup values remain unavailable; prices and volume are not backfilled.
3. Review the preview and both cost scenarios. Changes to the hypothesis, source,
   data or settings invalidate the review checkbox. **Add to Tasks** freezes the
   protocol and queues it; **Run now** also launches a bounded local worker.
4. **Tasks & matrix:** inspect queued/running/terminal states, progress, formula,
   source fingerprint, frozen scope, actual results and receipts. One local slot
   executes at a time. Identical requests reuse the existing task. Failed and
   cancelled requests remain retained and are not automatically retried.
5. **Portfolio:** inspect retained development accounts and normal/doubled-cost
   returns. Account comparison requires identical manifest, frequency, date
   range, starting capital and observed session calendars. Correlation requires
   at least 20 shared sessions with defined returns. Mean account equity is a
   diagnostic; combined portfolio risk and netting have not been replayed.

Every experiment is development-only and nonpromotable. A completed task means
the replay finished; formal eligibility has not been assessed. No registry
promotion, sealed TEST observation access, PAPER control or real orders occur.
Registered results retain their original statuses and evidence.

## Execution and recovery

Dates remain bounded to Jan 9–Jun 30, 2026, at most 31 calendar days per
candidate and 12 candidates per submission. Both cost scenarios use separate
accounts through the existing risk/OMS/venue/ledger path. Orders use the next
observed opening, long/flat targets and whole shares. Signals reset each session.
The NSE session adapter preserves original timestamps and uses their actual
09:15 IST grid phase rather than requiring an epoch-aligned hourly clock.

Queued cancellation is immediate. Running cancellation stops at a completed flat
session boundary; partial receipts remain retained. A stale worker can be marked
**INTERRUPTED** explicitly after at least 60 seconds without a heartbeat. This
revokes ownership; it never resumes or requeues trading. Do not repeatedly start
workers to recover a running task. Review retained evidence first.

State lives in ignored `local_state/research_lab/tasks.sqlite3` (SQLite WAL).
Worker output is `local_state/research_lab/worker.log`. Frozen protocols and
accounts are retained under `reports_out/research_lab/`. Source and manifest
identity are rechecked before execution. Source changes after preview require
a newly reviewed experiment. Result and protocol hashes are checked before
displaying performance. Old NSE sandbox accounts remain readable.

## Start locally

From the HELIOS folder in PowerShell, using the documented WSL runtime:

```powershell
wsl -d Ubuntu -- env PYTHONPATH=research PATH=/home/abhi/.venvs/helios-runtime-312/bin:/home/abhi/.local/bin:/usr/bin:/bin /home/abhi/.venvs/helios-runtime-312/bin/python -m streamlit run dashboards/streamlit/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

The frontend and local Python execution backend are part of this application.
The UI starts an independent bounded worker when requested. To process an
already-reviewed queue from another terminal:

```powershell
wsl -d Ubuntu -- env PYTHONPATH=research PATH=/home/abhi/.venvs/helios-runtime-312/bin:/home/abhi/.local/bin:/usr/bin:/bin /home/abhi/.venvs/helios-runtime-312/bin/python -m helios.dashboard.lab_worker --max-jobs 12
```

The registry additionally requires existing PostgreSQL. With Docker Desktop
running, start existing infrastructure without deleting volumes:

```powershell
docker compose --env-file .env -f infra/docker-compose.yml up -d
```

Registry connection failures are shown as unavailable, not zero activity.
Retained-data development replay does not require the registry database.
Do not publish `.env`, local queues, CSV exports or bulk market data.
