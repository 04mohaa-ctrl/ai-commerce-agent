# V2: evidence-backed product research

V2 extends the existing V1 app. Installation and launch commands in README are
unchanged. Research runs for one selected product; category search still finds
local candidates. No commerce automation, external browser automation or new
agent orchestration is included.

## Run product research

The Research page accepts **a product name or a category**:

- An exact existing name (for example Pet Hair Remover) selects that candidate,
  opens its Research tab and runs the same evidence-backed action used in Details.
- A category (for example Kitchen gadgets) continues showing relevant candidates
  from connected local/discovery sources. Select a candidate to research it.
- A new specific name (for example Electric heated lunch box) offers **Research
  this product**. One click creates/reuses a custom candidate and opens/runs the
  existing Product Details research flow. The manual form is optional.

Unmatched searches do not create candidates or make web requests until the
custom action is clicked. Custom names are normalized for case/spacing and
reuse existing candidates, preserving their sources and economics. A blank
search still lists candidates. New custom product costs/selling prices start
as unknown, not guessed numbers; all five Economics inputs may remain blank
until supplied. Unknown margins stay blank and sort last. Direct product
selection clears excluding filters so its details stay visible. Demo Mode and
keyless fallback apply identically to both research entry points.

1. Configure OPENAI_API_KEY privately in local `.env`. Never commit or paste it.
2. Optional: set OPENAI_RESEARCH_MODEL=gpt-4.1-mini. The V1 OPENAI_MODEL remains
   separate; the research model must support Responses web_search and Structured Outputs.
3. Start `.venv\Scripts\python.exe -m streamlit run app.py`.
4. In Settings, disable deterministic demo mode. This choice persists across navigation.
5. Choose a candidate, open Product Details → Research, then click Research product.
6. Review progress and the resulting evidence, confidence and Sources links.
7. Enter financial assumptions in Economics and save them explicitly.

Default demo mode makes no external requests, even with a configured key.
Without a key, Research product returns Insufficient evidence and a Demo Mode
notice with no invented sources. Previously collected evidence remains viewable.
Navigation, saving products and editing economics never call OpenAI. A web
refresh is explicit and may incur API charges; failures display a sanitized
status while retaining comparable prior evidence.

States: No research performed, Researching, Research completed, Research failed,
Insufficient evidence. A restarted/interrupted attempt is labeled for an explicit
retry. Insufficient evidence is a valid outcome; it does not mean the product
has low demand. Missing support is simply unknown.

## Provider and provenance

`src/research/providers/web_research.py` implements the ResearchProvider interface.
It makes a bounded Responses API web_search retrieval followed by Pydantic
structured classification. Tool-issued URL annotations provide the source
identity/title; the classifier cannot invent accepted URLs. Supporting excerpts
must match the cited context of every attached source. Adjacent citation markers
may support the same claim; unrelated sentences in a shared paragraph cannot
transfer their claims between citations.

Sources store title, canonical URL, UTC access time, source type and supported
claim context. Tracking parameters/fragments are removed for deduplication;
functional query parameters are retained. Every accepted finding links its
sources inline, and Sources also lists access times. A URL citation establishes
provenance, not independent verification of the publisher's statement.

- **VERIFIED / OBSERVED:** citation metadata and, when available, matching USD
  Product/Offer JSON-LD prices actually read from cited retail listings.
- **ESTIMATED:** user-entered costs, target selling price, fees and ad cost.
- **AI JUDGEMENT:** interpretations, qualitative demand/competition/trend/
  marketing classifications, source-linked search summaries, risks and recommendations.

The web-search prose is an AI summary of cited pages, not a verbatim quotation
from the original webpage. Its numerical market claims are not independently
verified statistics. V2 never derives an observed numeric price range from an
LLM guess: `providers/prices.py` accepts only matching USD Product/Offer metadata
from bounded HTTPS reads of allowlisted retailers. It uses no CSS selectors,
credentials or arbitrary-site redirect chain. Missing/blocked/incompatible
metadata leaves observed_price_range unavailable; it is not replaced by the
demo selling price. Listing prices may describe variants/promotions and do not
prove a market-wide range, sales volume or consumer demand.

API implementation follows [OpenAI web search](https://developers.openai.com/api/docs/guides/tools-web-search)
and [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
confirmed through Context7 and installed SDK types. Access to a model/tool can
vary by API account; demo and previous research remain usable if it is unavailable.

## Deterministic economics

Inputs are USD product_cost and selling_price, plus optional shipping_cost,
payment_fee_percent and estimated_ad_cost_per_order. Blank means unknown;
explicit zero is an assumption of no cost. All values are finite/nonnegative,
selling price is positive and percentage fees cannot exceed 100.

```text
gross_profit = selling_price - product_cost - shipping_cost
gross_margin_percent = gross_profit / selling_price * 100
payment_fee = selling_price * payment_fee_percent / 100
estimated_net_profit = gross_profit - payment_fee - estimated_ad_cost_per_order
estimated_net_margin_percent = estimated_net_profit / selling_price * 100
break_even_ad_cost = gross_profit - payment_fee
```

Decimal arithmetic rounds money and payment fees to cents before net-profit
arithmetic. Unknown dependencies stay unavailable; e.g. break-even CPA can be
calculated without ad cost, but net profit cannot. A negative break-even CPA
means the current offer loses money even before any advertising.

Known example: selling price USD40, product USD10, shipping USD5, fee 3%, ads
USD8 → gross profit USD25; gross margin 62.50%; fees USD1.20; net profit USD15.80;
net margin 39.50%; break-even CPA USD23.80. Taxes, returns, fixed payment fees
and overhead are excluded and need a later landed-cost/profitability extension.

## Evidence scoring and confidence

Before web research, V1 estimate scores remain available with low evidence
confidence. After web research, the table and metrics use the current evidence
score and show the score basis. This does not silently rewrite the old saved
JSON snapshot. Save/Update saved analysis remains an explicit action.

Weak/moderate/strong map to 3/6/9 out of ten. Unsupported demand/trend/marketing
contribute zero; unknown competition gives no competitive advantage. Weights
remain demand 25%, profit 25%, trend 20%, inverted competition 15%, marketing
15%. The V2 profit factor is clamp(estimated_net_margin_percent / 10, 0, 10).
Unknown net economics produces zero profit-factor points.

Confidence is a deterministic coverage heuristic: low unless demand,
competition and trend have accepted findings, with at least three independent
publisher domains. Otherwise medium. Web summaries are never classified as
high-confidence independent verification. Evidence over seven days old is
conservatively low confidence. Subdomain counting folds publishers conservatively
and may undercount shared country-domain suffixes; it is not an ownership audit.

The final weighted score is multiplied by 0.50 for low confidence or 0.85 for
medium, then rounded to one decimal. Score calculation shows normalized inputs,
weighted contributions, raw total and adjustment. Neither confidence nor score
is a calibrated probability of commercial success. V1's product-only gross
margin remains visible separately from Economics' after-shipping/net margins.

## Storage and compatibility

The repository migrates SQLite additively, in one transaction, to user_version 2.
Existing V1 saved_products/candidates rows remain intact. New tables:

- research_records: latest report per canonical product, including input fingerprint,
  research timestamp, qualitative dimensions and confidence.
- research_sources: unique canonical sources linked to that report.
- research_attempts: latest attempt/status, separate from retained usable evidence.
- economics: latest explicit financial assumptions per product.

Repeated saves and refreshes do not create duplicate source/report rows.
Failed/no-evidence refreshes retain usable comparable prior evidence; fresh
partial evidence for a changed product fingerprint replaces obsolete research.
Changed description/category/tags invalidate cache/display reuse. Cache reuse
is bounded to one day; the UI Research product button explicitly refreshes.
Research/economics persist even for unsaved candidates. Removing a shortlist
entry does not delete its independently collected research.

Back up the SQLite file with the app stopped, or use sqlite3's backup API.
The stable V1 Git tag remains unchanged. V2 can read V1 snapshots; rolling an app
back to V1 against V2-created snapshot fields is not guaranteed, so use a matching
pre-migration database backup when rolling back versions.

## Tests and next step

Run `.venv\Scripts\python.exe -m pytest`. Original V1 tests remain unchanged.
V2 tests use fake HTTP transports and temporary databases, covering real SDK
request/parsing paths, provenance, missing/failed research, duplicates, migration,
unknown economics, confidence and Streamlit flows. Test runs make no paid API calls.
Actual live verification is separate and recorded in `verification-v2.md`.

Next: add publisher publication dates, page-level evidence verification and an
additional provider for measured demand/time-series data. Then extend net
economics with returns, taxes and landed supplier costs before launch decisions.
