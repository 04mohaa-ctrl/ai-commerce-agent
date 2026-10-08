# Released V4 supplier selection diagnosis — 8 October 2026

This records the first debugging pass. The follow-up
[workflow completion](v4-workflow-completion.md) supersedes its description-only
input and unchanged-startup instructions with structured supplier preferences,
quote selection, diagnostics and normal-startup provider configuration.

Verified baseline: HEAD/main and the peeled annotated v4.0.0 tag are
`b34e5fc7a520f72d302d65a3a1b5bf9984ac11c7`. Work is on
`codex/v4-supplier-requirements-fix`, without commits or release operations.
Historical verification prose was treated as context; the findings below come from
current code, read-only SQLite queries and offline replay of actual saved observations.

## Root cause and classification

The saved Foldable Laptop Stand description is:
“Adjustable aluminum stand for laptops in a compact desk setup. Load and stability
need testing.” Neither its name nor description declares color. `_details()` therefore
returns no target attributes. CJ normalization correctly retains the variant's
documented `variantKey` as `{"variant_key": "Black"}`. The matcher parses black from
both the variant name and that combination label. Parsing is already working.

`match_supplier()` compares attribute declarations from the target name/description
against the candidate name, variant name/attributes and candidate brand. Its symmetric
missing-attribute check treats an observed supplier color without a comparable target
color as missing evidence, so this stand becomes AMBIGUOUS, missing `color`, without
contradictions. That conservative behavior is intentional and remains in place.
Explicit target black produces MATCH for the genuine black stand; explicit white
produces NO_MATCH. Unspecified is not implicitly “any color.”

The exact UI gate constructs a SupplierSelection and calls `selection_issue()`.
It rejects AMBIGUOUS/NO_MATCH, contradictions and missing decisive attributes.
LIKELY_MATCH additionally needs an explicit checkbox confirmation containing the
actual observed attributes; confirmation cannot clear missing requirements. Stock
success is independent of this identity gate. Saved CJ stock is 0 and factory stock
12829; the normalized total is 12829 in warehouse 1, storage
`{6709CCD7-0DC7-43B1-B310-17AB499E9B0A}`, origin CN. This is an observation, not an
assurance of dispatch. Shipping remains pending until explicit compatible selection.

There were two practical defects:

1. Saved products exposed estimated prices and score assumptions but no target
   requirements editor. The manual Research input could carry `Color: Black` in a
   description, but it was not a practical correction workflow for a saved product.
2. Identity matching used word overlap. The saved laptop phone side-mount listing
   contained all target identity words. In memory, adding target black changed that
   accessory from AMBIGUOUS to LIKELY_MATCH, which would allow a mistaken confirmation.

## Focused correction

Data & assumptions now offers a target-description/variant-requirements form. Saving
is an explicit local action: it updates the target description in the saved analysis,
updates an existing manual candidate and session result, and recomputes matching from
the saved supplier observations. Name/category and product ID remain stable. No live
research or model analysis runs. Existing analysis is labeled historical. The current
report's input fingerprint is updated; provider observations, source times, stages,
telemetry and collection destination are preserved. No schema/configuration change.

A deterministic supplier identity check rejects phone side/monitor mount holders
as laptop support stands, both before enrichment and during final matching. It checks
candidate and variant titles. A laptop stand described as having an optional phone
holder remains eligible for ordinary identity review. This is a focused accessory
distinction, not a general semantic catalog classifier.

The UI recomputes matches before exposing selection controls, including old reports.
Historical selections are preserved but financial applicability is checked against
current inputs/classification. Shipping also rejects a historical selection when its
classification disagrees with the current rechecked offer. Local rechecking never
renews supplier price/stock/freight freshness or selects/adopts anything automatically.
Supplier cost still requires price evidence within 24 hours; stock/freight checks retain
their 6-hour windows, exact identities, destination, quantity and quote expiry rules.

## Shortlist, selection and economics

`supply_v4_shortlist` stores a full serialized offer snapshot plus Preferred/Backup,
notes and saved time. Its key hashes product ID plus offer snapshot ID; changing
warehouse, shipping method or observations yields a distinct snapshot. The UI displays
only role, variant ID and notes. The saved “Preferred · 1CC71DF3-9C07-43FD-9B78-074266306AD0
· This one” entry did not approve compatibility. There was no supplier selection or
V4 financial record in the authoritative database.

`supply_v4_selection` separately stores an explicitly chosen immutable offer snapshot,
confirmation and selection time. Selecting does not change costs. Only **Apply observed
supplier cost**, **Apply current shipping quote**, or an explicit manual economics save
changes the separate financial snapshot/provenance. Requirement edits preserve both
shortlist and historical selected/adopted values; incompatible adopted observations
lose current eligibility rather than having their stored values silently rewritten.

## Exact UI workflow

1. Launch the fix checkout on a free port using the dotenv command below. Open
   **Saved Products**, choose **Foldable Laptop Stand**, and open **Data & assumptions**.
2. Preserve the existing description. If black is actually the intended target variant,
   append a separate line `Color: Black` (or `; Color: Black`). Declare other decisive
   requirements truthfully. If color is unknown, leave it unspecified; it remains
   AMBIGUOUS and can be shortlisted for further investigation.
3. Click **Save target requirements and recheck saved offers**. This is offline and
   changes your target inputs only on your explicit submission. Reopen **Supplier
   Intelligence** after the rerun. The genuine black stand should show MATCH; grey and
   phone side-mount offers are NO_MATCH. Any other unresolved offer remains blocked.
4. Confirm product ID `4C56FFFA-399B-4E05-98C6-092BB3A724A9`, variant
   `1CC71DF3-9C07-43FD-9B78-074266306AD0`, warehouse 1 and the storage ID above.
   Click its **Select this offer**. Reopen Supplier Intelligence if the rerun returns
   to Analysis. V4 cost remains the prior assumption until adopted explicitly.
5. For subsequent live research, configure CJ, turn Demo Mode off in Settings, and
   explicitly **Refresh supplier data** if observations are stale. Review and select
   the updated offer. Then **Refresh shipping** for Sweden, quantity 1, maximum 14 days.
   These refresh buttons make provider requests; they were not used live during this
   debugging session. No cached freight quote was available to verify actual delivery.
6. Review the returned freight method/cost/delivery and explicitly select the desired
   offer with that quote. Use **Apply observed supplier cost** and **Apply current
   shipping quote** separately in V4 economics. Unknown fields stay unknown; selecting
   or shortlisting alone never changes financial assumptions.

## Reliable dotenv launch

From the repository directory in PowerShell, choosing an unused port:

```powershell
.\.venv\Scripts\python.exe -m dotenv -f .env run --no-override -- .\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

`load_settings()` uses dotenv_values without mutating the process environment. CJ's
transport and DataForSEO's adapter read environment variables directly. An ordinary
Python probe reported OpenAI settings configured, CJ false, DataForSEO false; the same
probe under the dotenv launcher reported all three true. Only booleans were emitted.
`--no-override` preserves existing environment values, including an explicitly empty
variable. Configuration behavior and `scripts/start.ps1` remain unchanged.

## Validation and preservation

Baseline: 676 tests passed. Regression tests failed before fixes for the missing
editor and incorrect phone-holder identity, then passed. Additional shipping tests
failed before the historical-selection guard and passed afterward. The checked-in
fixture preserves sanitized saved observations and original times. It covers genuine
stand, unspecified/matching/conflicting colors, grey mismatch, side-mount rejection,
ordinary stand with phone-holder feature, local recheck, persistent requirements,
identity/time preservation, stale price refusal and explicit financial adoption.

Actual browser verification used an isolated database and Streamlit on 127.0.0.1:8517.
All provider HTTP sends were prohibited and process credentials were empty. The
unchanged target initially blocked selection. Saving black enabled the genuine offer;
selecting preserved USD 8.90; explicit adoption changed only the test V4 cost to USD
3.10. Saving white disabled all offers and supplier-cost adoption while retaining
the historical selection and adopted USD 3.10. Blank color restored AMBIGUOUS.

The user database and .env are read-only during diagnosis and are checked by SHA-256
before/after. No live CJ, DataForSEO or OpenAI calls, orders or payment actions. Existing
user servers are preserved; only the isolated test server is stopped after verification.
Final verification: 687 tests passed; `ruff check .`, formatting checks for changed
Python files and `git diff --check` passed. SHA-256 equality confirmed the original
database and .env unchanged, with the original description still lacking color and
no selection or V4 financial record added to that database.

Changed implementation: src/supply/matching.py, src/supply/service.py,
src/ui/products.py, src/ui/supplier_intelligence.py. Added regression test/fixture:
tests/test_supply_requirements.py, tests/fixtures/v4_laptop_stand.json. Documentation:
README.md and this file. Disposable probes/databases/screenshots remain ignored
under artifacts/.
