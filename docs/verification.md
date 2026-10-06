# V1 verification — 2026-10-06

Environment: Windows, Python 3.12.14, Streamlit 1.65.0, OpenAI SDK 2.54.0,
Pydantic 2.13.5, pytest 9.1.1. Exact installed dependencies are recorded in
requirements-lock.txt. Tests use temporary databases and no real API requests.

## Automated results

- `.venv\Scripts\python.exe -m pytest -q --tb=short`: **56 passed** (11.13 s).
- `.venv\Scripts\ruff.exe check . --output-format concise`: **All checks passed**.
- `.venv\Scripts\ruff.exe format --check .`: **29 files already formatted**.
- `.venv\Scripts\python.exe -m compileall -q src app.py`: exit 0.

Coverage includes deterministic weighted arithmetic, inverse competition,
negative margins and invalid numerical/text inputs; seed diversity and search;
sorting/filtering and empty states; SQLite save/update/duplicate prevention,
reopen/remove/manual candidates and controlled corrupt-data errors; missing-key
demo and explicit demo with a configured key; real OpenAI SDK parsing over a
mock HTTP transport, refusal, invalid schema, unauthorized requests, timeout and
safe fallback; and Streamlit AppTest user flows.

The AppTest flows cover dashboard data and details, query submissions, empty
search recovery, save/update without duplication, a new app session reading
saved data, removal, manual entry and persistence, keyless settings and database
startup failure. A live-mode regression submits research after navigating away
from Settings and rerunning; the resulting rows must remain OpenAI analyses.
Only the external SDK request boundary is substituted in this UI test; request
payloads and response parsing are separately covered with the real SDK.

## Independent review and fixes

A read-only reviewer inspected the complete implementation and reproduced two
important bugs. Both were reproduced with failing regression tests and fixed:

1. Settings-only widget cleanup erased the chosen live mode. The durable
   `use_demo` session value now lives independently of the temporary toggle.
2. Searching old seed tags could resurrect superseded prices after a manual
   override. Canonical manual records now shadow seed records for every query.

Review also found malformed text types causing raw TypeError before Pydantic
validation. Three failing tests for null/numeric names and null category were
added; string type validation now runs before normalization. All tests then
passed. Currency prose uses USD to avoid Streamlit Markdown interpreting pairs
of dollar signs as mathematical notation.

## Real server and browser checks

Started the server with:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

- `GET http://127.0.0.1:8501/_stcore/health`: `ok`.
- `GET http://127.0.0.1:8501`: HTTP 200.
- Opened the actual app and verified 12 demo products and numerical scores.
- Used Research to analyze `pet accessories`: 2 matching candidates.
- Opened Pet Hair Remover details and saved it through the real UI.
- Stopped that server process and started a new server process on the same port.
- Reloaded the browser, opened Saved Products and found the one saved product,
  retaining its earlier analysis timestamp, reasoning and 75.4 score.
- Confirmed the final USD price display in the updated server.

The app remains running on port 8501. The default SQLite database retains the
Pet Hair Remover demo snapshot used in this check. Screenshot:
`artifacts/saved-after-restart.png` (local, Git-ignored).

## Scope and limitations

No real OpenAI call was made: SDK request construction, parsing and fallback
were tested with simulated transport, but remote schema acceptance, account/model
access and generated-analysis quality need a real configured API run.

Only local seed/manual products are searched. V1 contains no scraping, automated
ordering, payments, Shopify/ad integrations, hosted deployment, multiuser access
or agent orchestration. External discovery and source validation are next-stage
work. Sequential analysis is capped at 20 products per query; live analysis can
be slow if several requests time out. Scoring represents estimated gross margin
and subjective judgements, never verified net profit or a success probability.
