# Local registry dashboard (155)

From the repository root in the documented WSL environment:

```bash
/home/abhi/.venvs/helios/bin/python -m streamlit run dashboards/streamlit/app.py \
  --server.address 127.0.0.1 --server.port 8501 --server.headless true \
  --browser.gatherUsageStats false
```

Open `http://localhost:8501`. Database settings come from the existing local
environment; passwords and connection exceptions are not rendered. The dashboard
uses repeatable-read, read-only transactions. There are no fit, evaluate, promote,
TEST-access or order controls. Derived HTML files are isolated under ignored
`reports_out/dashboard/<run UUID>/`; original evidence is not changed.

All registered versions appear, including DRAFT and explicitly marked synthetic
definitions. Measurement status and the separate round-one selection decision
remain different columns. A name search and horizon filter limit both tables.
The second table preserves every retained measurement, including INVALID attempts
and multiple instruments/runs. Unavailable performance stays null, not zero.

Report links open a canonical retained-run UUID in the same app. The report is
generated from checksum-verified saved evidence, with a downloadable HTML copy.
Changed evidence or an invalid identifier fails visibly instead of displaying an
unverified result. Definitions without measurements have no report link.

Actual browser verification on 2026-10-15 showed all 13 definitions (12 research
plus the synthetic fixture), all 22 retained INVALID attempts, and the original
`hourly_h01` VALID report with unavailable performance and its original lineage.
Four dashboard/database/AppTest cases cover DRAFT inclusion, filtering, unsafe
report paths and sanitized connection errors; strict typing also passes.
Two additional regressions cover inert spawn reimport and a real worker with the
dashboard entrypoint and invalid database settings. Page rendering lives behind
guarded `main()` so workers never initialize UI or read the registry on import.

This is a local research view, not a published service or a change to strategy
selection. Subsequent minute registrations appear through the same queries.
API reference: [Streamlit dataframes](https://docs.streamlit.io/develop/api-reference/data/st.dataframe).
