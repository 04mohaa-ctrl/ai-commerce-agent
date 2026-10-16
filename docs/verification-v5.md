# V5 verification and handoff

**16 October acceptance follow-up:** the approved
[bounded V5 live acceptance passed](v5-live-acceptance-20261016.md): auth1/search1,
three genuine saved candidates, restart,
comparison and browser export, with zero follow-up provider calls. The [preparation/review
record](v5-acceptance-20261016.md) supersedes the earlier one-review statement and generic
live-preparation limits below. Earlier synthetic observations remain synthetic.

## Verified baseline and workspace

Local main and read-only `git ls-remote origin refs/heads/main` both resolve to
`124c1f741aa584cf6c2444b52407992863a754f4`. Clean baseline: **723 passed** in 102.47s.
The original checkout remains on `codex/v4-supplier-requirements-fix` at `1a72806`.

V5 branch: `codex/v5-discovery-comparison`.
Worktree: `C:/Users/Användar/.codex/worktrees/v5-discovery-comparison/ai-commerce-agent`.
Implementation and acceptance were completed before the separately authorized feature-branch
commit/push. No merges, tags, purchases, billing changes or deployments were performed.
No existing app server was stopped and no existing operator database was opened or modified.

The initial sandbox attempt could not create the default system pytest temp directories;
that environment-error run is not a product validation result. All acceptance runs use fresh
temporary directories under ignored `artifacts/` with authorized worktree access.

## What changed and how to use it

Open **http://127.0.0.1:8510**. This server uses `COMMERCE_OFFLINE=1` and the separate
`data/v5-acceptance.db`; providers are disabled. The three seeded candidates are explicitly
**SYNTHETIC** and do not demonstrate real supplier stock, quality, availability or demand.

- **Discover:** submit a CJ keyword, optional inventory country, exact category ID and USD
  price range. One page per action, at most 10 results; request page 2 explicitly using the
  submitted filters. Images and links are displayed only if supplied and validated. A
  catalog price is neither a chosen variant price nor a landed cost. Save candidates locally.
- **Candidates:** select a saved candidate, declare target attributes, research the pinned
  supplier identity, explicitly select a compatible variant/warehouse and shipping quote.
  Adopt product cost and freight separately in V4 economics; enter the remaining costs,
  output/import VAT and any manual customer-price FX assumptions. Unknowns remain blank.
- **Review demand queries:** the original name stays visible. Swedish/English suggestions
  are unverified suggestions. Enter chosen terms using `sv:` / `en:`, save the reviewed plan,
  then submit that precise scope. Extra terms remain separate exploratory evidence. The
  existing full Research product action explicitly describes its original-name V4 query.
- **Compare:** select 3–5 saved candidates, name a group, inspect scenario consistency,
  missing inputs, evidence coverage/confidence and next actions. Save a decision and notes.
  Export contains the group plus current V4 evidence, observations, financial provenance,
  query series and gates. There is no guaranteed winner or missing-as-zero ranking.

The default Dashboard and all earlier Research/Saved Products flows remain available.
V5 workflow pages avoid unrelated demo-ranking metrics. Technical request data and raw
evidence are in expanders. Existing scoring, selection and economics meanings remain V4.

## Automated verification

Final full suite: **770 passed in 142.73s**, recorded in
`artifacts/full-v5-acceptance-20261016.log` (ignored local evidence). Production code,
scripts and tests were compared by Git blob identity against the snapshot after that run:
all 134 non-documentation files matched. The user authorized reuse of that validation for
the commit; subsequent changes are documentation only. Ruff lint/format and staged whitespace
and secret checks run separately before publication.
Earlier V5 validations were 759 passed in 254.09s and focused UI verification of 11 passed.

Commands use the existing interpreter with locked dependencies, from the V5 worktree:

```powershell
& 'C:/Users/Användar/Documents/ChatGPT/ai-commerce-agent/.venv/Scripts/python.exe' -m pytest -q --tb=short --basetemp=artifacts/final-v5-temp
& 'C:/Users/Användar/Documents/ChatGPT/ai-commerce-agent/.venv/Scripts/python.exe' -m ruff check .
& 'C:/Users/Användar/Documents/ChatGPT/ai-commerce-agent/.venv/Scripts/python.exe' -m ruff format --check .
& 'C:/Users/Användar/Documents/ChatGPT/ai-commerce-agent/.venv/Scripts/python.exe' -m compileall -q app.py src scripts
git diff --check
```

`tests/conftest.py` blocks both default HTTPX requests and HTTPcore socket connections.
Provider contract tests inject mock transports; AppTest uses isolated SQLite files. No keys
or external provider connectivity are needed. No paid/live API submissions occurred.

New coverage includes catalog filters, scalar/range/malformed prices, partial parsing,
page caps, exact cache compatibility, stale cache invalidation, duplicate identities,
same-name distinct supplier IDs, atomic failure rollback, synthetic-to-live blocking,
saved CJ IDs and variant IDs, separate case-distinct query series, partial failed demand
batches, deadline stops, body bounds, restart persistence, saved groups, group switching,
per-product query editors, geography/quantity/currency/tax incompatibility, currency labels,
five complete manual scenarios, unknown economics, read-only comparison/export, local
binding/offline credential guards, schema-5 activation/backup and non-overwriting restoration,
full export and logical product deletion. Existing V4 tests retain wrong-product/accessory
rejection, conflicting variants, sparse/stale/failed/empty results, explicit adoption,
VAT/import VAT/manual FX, freight precision, freshness, confidence and scoring gates.

## Actual browser acceptance

Used the Codex in-app browser at the exact loopback URL, including its narrow viewport:

1. Opened Discover, loaded labeled synthetic examples and verified all three saved identities
   showed duplicate prevention. Separate AppTest starts empty and saves all three through UI.
2. Opened Lunch box: the incompatible 500ml variant was `NO_MATCH` with selection disabled;
   the intended target was 1000ml. Eight-day-old evidence stayed historical/ineligible.
3. Opened Laptop stand: a side phone mount was rejected. Selected the exact compatible
   variant `SYNTHETIC-V1-0` and observed warehouse. Adopted product USD 6.00 and freight
   USD 9.25 using two separate buttons; other unknown economic inputs remained unknown.
4. Verified English/Swedish query plans changed with the product. Each sparse demand series
   showed only 3/52 usable bins and `INSUFFICIENT_DATA`; no interest magnitudes were added.
5. Opened the three-member group. It correctly reported incomplete scenarios and no direct
   comparability. Saved **Investigate** and reasons explicitly disclaiming any purchase decision.
6. Downloaded the actual comparison JSON and parsed it locally. It contained schema
   `ai-commerce-v5-comparison-1`, all three products, the saved decision, exact selection,
   adopted 6.00/9.25 costs, separate `Laptop stand` / `laptopställ` snapshots, and
   `directly_comparable=false`. Local copy: `artifacts/browser-comparison.json`.

AppTest also creates a fresh session and verifies saved groups; the full recovery tests
restore into a different DB. Narrow-screen navigation requires opening the sidebar and
wide comparison tables scroll horizontally. No live provider behavior is inferred from UI tests.

An additional CLI backup/restore of the browser's acceptance database recovered all three
products, the Investigate decision, `SYNTHETIC-V1-0`, and adopted costs 6.00/9.25 into
`data/v5-restored-check.db`. Only the V5 server created for this task was restarted with
`scripts/start-v5.ps1`; existing servers were preserved. The app uses the same isolated DB.

## Independent read-only review

A separate reviewer inspected the uncommitted code against the requirements. Material
findings were addressed with reproducing tests:

- Group switch state: `test_switching_groups_loads_correct_members_and_notes` failed before
  owner-scoped editor initialization and passed after.
- Partial candidate writes: injected SQLite failure reproduced orphaned candidate/origin
  state; the save is now one transaction, including destination and snapshot.
- Demand total deadline: HTTPX operation timeouts did not justify a batch duration claim;
  the request now uses the existing absolute-deadline transport plus bounded streaming.
- Currency labels: V5 now reuses V4 values with currency-neutral scenario labels and a
  separate currency field; observed supplier prices retain their native label.
- V4 rollback ambiguity: V5 activation now verifies a pre-V5 schema-4 backup and writes
  schema 5 transactionally. Old apps reject the new version. V5 reads V1–V4 records; rollback
  uses the backup, preserving both files. Ordinary legacy serialization omits null V5 identity.

The reviewer did not perform live calls, edit files, inspect secrets or examine user databases.
The later independent review also checked widget cleanup, bounded DNS and migration/replay
races. Its confirmed fixes and regression evidence are recorded in
[the acceptance preparation](v5-acceptance-20261016.md).

## Limitations and launch decisions

- CJ catalog cache account nonces are process-local. Compatible cache reuse works within a
  process; after restart, the app conservatively requires an explicit new request rather
  than assume account compatibility. Successful saved candidates/evidence/groups persist.
- The bounded keyword/page catalog flow is live verified. Optional filters and failure cases
  remain fixture verified. The separate synthetic demo's stock/freight/demand stays synthetic;
  existing V4 captures retain their historical provenance. For the three new genuine V5
  candidates, variants, stock, freight, delivery, demand and economics remain unverified.
- Additional demand queries do not alter V4 opportunity scores. Compare separate series'
  evidence quality/trend within its own context, never independent index magnitudes.
- No multi-user implementation: no authentication, per-user ownership or daily spending
  ledger. The app is loopback-only and suitable for one trusted operator. API credentials
  remain server-side, one account set per process. Local rate/action caps are not dollar quotas.
- Deletion is logical and removes referencing groups/caches; backups and downloaded exports
  deliberately remain. Retention, backup expiry and secure erasure require operational policy.

See [the code-backed launch checklist and effort assumptions](v5-readiness.md). Separate local
tester installations are the smallest beta option; isolated hosted instances or a shared
service need explicit hosting/credential-funding choices. No deployment has been performed.
