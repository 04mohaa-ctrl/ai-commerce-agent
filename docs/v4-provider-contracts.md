# V4 provider contracts

Accessed2026-10-07. Official docs verified with web and Context7
/websites/developers_cjdropshipping. No unofficial scraping or inferred routes.

## CJ

Host https://developers.cjdropshipping.com; CJ-Access-Token on research GET/POST.
Exact allowlist (all paths prefixed /api2.0/v1/):
- POST authentication/getAccessToken: apiKey; returned access/refresh tokens and
  expiry timestamps. POST authentication/refreshAccessToken: refreshToken.
- GET product/listV2: keyWord,page,size; data.content[].productList[].id/nameEn.
- GET product/query: pid; data.pid/productNameEn/variants.
- GET product/variant/query: pid; data[].vid/pid/variantNameEn/variantKey,
  variantSellPrice USD, dimensions mm/volume mm3/weight g.
- GET product/stock/queryByVid: vid; data[].areaId/countryCode/totalInventoryNum,
  stock[].stockId/inventory/factoryInventory. Preserve CJ/factory distinctions.
- POST logistic/freightCalculate: startCountryCode,endCountryCode,
  products[{quantity,vid}],optional storageIdList. logisticPrice USD quote,
  logisticPriceCn CNY (never combined),logisticAging,logisticName, optional fee totals.

Catalog prices do not establish variant availability. Currency/tax inclusions,
account discounts and binding checkout prices are not inferred. Only variant
price metadata and explicit one-variant quotes are candidates for cost application.
Area IDs are not subwarehouse IDs. Missing warehouse binding blocks applicable
freight; delivery/tracking absent stays unknown. freightCalculateTip is unsupported
because its extra parcel/product-property semantics are outside implemented V4.
No order/payment/balance/publishing/fulfillment routes are callable.

Sources: [auth](https://developers.cjdropshipping.com/en/api/api2/api/auth.html),
[catalog/variant/stock](https://developers.cjdropshipping.com/en/api/api2/api/product.html),
[freight](https://developers.cjdropshipping.com/en/api/api2/api/logistic.html).

Auth docs currently say180-day lifetime and24h server token reuse; use actual
returned expiries, not hardcoded validity. Conservative1request/sec covers Free
tiers, with account/IP constraints; point quota exhaustion is RATE_LIMITED.
HTTP429 and1600200/1600201/16900500 are rate/quota outcomes. These
are distinct from local BUDGET_EXHAUSTED stops: no dispatch after the request cap
or action deadline. limit_source identifies LOCAL_REQUEST_BUDGET, LOCAL_TIME_BUDGET,
PROVIDER_RATE_LIMIT or PROVIDER_QUOTA_LIMIT. An actual HTTP429 stays RATE_LIMITED
when retry_blocked_by records a local budget constraint. Historical ambiguous
budget notices can identify only LOCAL_ACTION_BUDGET; unknown origins stay unknown.
Auth errors1600001..1600008 are sanitized. Retry only documented busy1600000/timeout1600301
or transient HTTP failures, at mostonce inside budgets, respecting Retry-After.
[Limits](https://developers.cjdropshipping.com/en/api/start/limit.html),
[error codes](https://developers.cjdropshipping.com/en/api/api2/standard/ps-code.html).

## DataForSEO

Reuse generic V3 DemandTrendProvider. POST
https://api.dataforseo.com/v3/keywords_data/dataforseo_trends/explore/live;
HTTP Basic with process DATAFORSEO_LOGIN/PASSWORD; both required. One Live task in
one POST, one exact visible keyword, explicit country code and closed date range.
Returned type trends/dataforseo_trends_graph; numeric values are provider-relative
popularity, not monthly search volume/sales/buyers. Raw0 is insufficient data.
Live API permits2000requests/minute,30concurrent; V4 uses1/action with no automatic
retry or separate retrieval. Preserve query/location/period/granularity/series ID.
Mappings US2840,GB2826,SE2752,DE2276,FR2250 were verified against the official
[supported-country CSV](https://cdn.dataforseo.com/v3/locations/locations_dataforseo_trends_2026_09_01.csv)
linked by the locations documentation. DefaultUS retains V3. Credentials absence
or unsupported mapping leaves other stages usable. Unsupported country dispatches
no measurement. One shared research action imports its comparable V3 cache; it
does not issue a second paid measurement. Standalone explicit refresh bypasses cache.
[Endpoint](https://docs.dataforseo.com/v3/keywords_data-dataforseo_trends-explore-live/),
[locations](https://docs.dataforseo.com/v3/keywords_data-dataforseo_trends-locations/),
[limits](https://dataforseo.com/help-center/rate-limits-and-request-limits).

## Libraries and display links

Existing HTTPX0.28/Pydantic2/Streamlit1.65/SQLite/Decimal only; no new supplier SDK.
Bound HTTP response bodies, trust_env=False, redirects=False. Parse only fields
listed above and discard secret/error payload bodies. Sanitized HTTPS links may
be opened by users, never fetched with provider credentials.
