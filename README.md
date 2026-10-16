# AI Commerce Agent

## V5 local development build

V5 adds **Discover → Candidates → Compare** using the existing CJ and V4 research,
supplier-selection, economics and evidence services. This feature is developed on
`codex/v5-discovery-comparison`, based on verified main
`124c1f741aa584cf6c2444b52407992863a754f4` (723 passing baseline tests).

Open [http://127.0.0.1:8510](http://127.0.0.1:8510) for the isolated **offline acceptance**
app. Its three example products, stock, freight and demand data are explicitly synthetic.
They are not live supplier observations. Existing operator databases and servers are preserved.

The separate [bounded V5 catalog acceptance](docs/v5-live-acceptance-20261016.md) passed:
one authentication and one keyword search, three genuine saved candidates, duplicate checks,
restart persistence, comparison and export. Its offline viewer is http://127.0.0.1:8512.
For these candidates, **variants, stock, freight, delivery, demand and complete economics
remain unverified**. Listing prices were not adopted as costs. The full offline suite passed
770 tests; historical V4 live evidence remains separate from this catalog-only acceptance.

1. **Discover:** explicit CJ keyword search with country/category/price filters; at most two
   pages of ten products. Save candidates without adopting catalog prices. Demo Mode blocks APIs.
2. **Candidates:** specify requirements, select exact variants/warehouses/shipping methods,
   research, then explicitly adopt costs. Review Swedish/English terms and save a query plan
   before requesting additional demand series. Suggestions never replace the original product.
3. **Compare:** choose 3–5 saved candidates, save a named group and decision reasons, inspect
   incompatible assumptions and missing inputs, and export current V4 evidence plus V5 context.

For a fresh offline workspace, with the locked dependencies installed:

```powershell
.\scripts\start-v5.ps1 -Port 8510 -DatabasePath data/v5-local.db
```

An isolated worktree can reuse an existing interpreter via `-PythonExecutable FULL_PATH`.
`-LiveProviders` enables configured providers; it does not submit requests on startup.
Configure keys privately in this worktree's ignored `.env` or process environment. No keys
were copied during implementation. Direct local startup can also set `COMMERCE_OFFLINE=1`.

The first V5 write activates schema 5 only after verifying a pre-V5 backup. V5 reads old
data; V4 rollback uses that backup at a new path. See [readiness and recovery](docs/v5-readiness.md)
and [validation](docs/verification-v5.md). Local use is supported for one trusted operator;
shared hosted private beta and public launch remain blocked by ownership/auth/quota and
operational requirements. No login screen has been added to imply multi-user safety.

## V4 real demand and supplier intelligence

V4 adds **Supplier Intelligence** in Product Details to the existing research flow.
Declare the customer country and quantity before research. Optional read-only CJ
catalog, variant, warehouse stock and freight observations support explicit offer
selection and a local Preferred/Backup shortlist. Nothing purchases or publishes.

Supplier refresh does not replace a selection or its adopted costs. Review and
select updated observations explicitly, then **Apply observed supplier cost** or
**Apply current shipping quote** in the separate V4 economics form. Unknown costs
stay blank; enter zero explicitly. V4 can record a manual customer-price conversion
to USD with an explicit rate, date and source; no FX provider is called. Original
V1/V2/V3 saved products, economics and `market-v3` score meanings are preserved.

Only Research product, Refresh supplier data, Refresh shipping and Refresh demand
can call providers. Navigation and local saves make no requests. Demo Mode disables
all external providers. CJ and DataForSEO can run independently of the OpenAI key.
Set `CJ_API_KEY`, or both `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD`, privately in
`.env` or the process environment. Normal app startup loads missing optional provider
variables from `.env`; existing environment values, including empty values, win.
Credentials are never entered in the UI or DB. No new dependencies are required.

Normal launch now configures the optional providers reliably (PowerShell, from the
project directory, using a free port):

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

Choose a free port; preserve existing servers. `app.py` loads only absent CJ and
DataForSEO variables before rendering. The same applies to `scripts/start.ps1`.
OpenAI settings retain their existing dotenv precedence. Startup makes no provider
requests. The explicit dotenv wrapper remains available when you want to load the
whole dotenv environment without overriding existing variables:

```powershell
.\.venv\Scripts\python.exe -m dotenv -f .env run --no-override -- .\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

In saved Product Details, **Supplier Intelligence** and **Data & assumptions** expose
a structured **Required supplier color** field. **Save supplier requirements and
recheck** updates product-scoped supplier preferences without editing the product
description or calling providers. Unspecified color stays ambiguous; a color match
cannot turn a phone side-mount accessory into a laptop support stand. Freight has
an explicit **Shipping method for selected variant → Select shipping quote** step;
product-cost and freight adoption remain separate. See
[workflow completion and verification](docs/v4-workflow-completion.md).

V4 economics now requires an explicit selling-price VAT basis and import-VAT
assumptions. Unit costs scale with units per order; fixed payment fees, expected
return losses and ads apply once per order. Payment percentages use the customer
charge including output VAT; revenue excludes it. Adopted freight preserves the
exact order total despite rounded unit display. Results list their missing inputs.
**Saved Products → V4 comparison and evidence export** compares current V4 results
and exports JSON with observations, unknowns, assumptions, provenance and score gates.
See [daily-use readiness and acceptance](docs/v4-daily-readiness.md).

DataForSEO Trends measures **relative search-interest / popularity**, not monthly
search volume or sales. Current country mappings support US, GB, SE, DE and FR.
Page support verifies attribution to the publisher, not independent truth.

The first explicit V4 write verifies an ignored SQLite backup at schema 3 before
transactionally activating schema 4. Merely opening an old product does not migrate.
Untouched V3 cannot read schema 4; rollback uses the matching pre-V4 backup and must
preserve both databases. See [V4 design and usage](docs/v4-real-demand-supplier.md),
[provider contracts](docs/v4-provider-contracts.md), [implementation plan](docs/v4-implementation-plan.md)
and [verification](docs/verification-v4.md) for formulas, gates, setup and limitations.

## V3 market intelligence

V3 extends the same research action with bounded page support, optional native
DataForSEO relative popularity, compatible listing prices, separate landed/return
economics and deterministic explainable scoring. V1/V2 saved scores and economics
remain readable. No providers run on navigation or financial saves.

See [V3 architecture and usage](docs/v3-market-intelligence.md) and
[V3 verification](docs/verification-v3.md). DataForSEO is optional and disabled
without both process-environment credentials; unavailable measured data never
blocks the app. Page support confirms publisher attribution, not objective truth.

**Historical V4 release:** `v4.0.0` at `b34e5fc7`.
Verified main now includes the later V4 fixes at `124c1f741aa584cf6c2444b52407992863a754f4`.
Current V5 work is isolated on `codex/v5-discovery-comparison`.
Earlier stable releases remain tagged `v1.0.0`, `v2.0.0` and `v3.0.0`.
All original demo, manual-product and saved-product flows remain supported.

V2 adds **Research**, **Sources** and **Economics** tabs in Product Details,
current web research through the OpenAI Responses API, source-linked findings,
deterministic evidence confidence, net-margin scoring and durable financial
assumptions. Read [V2 usage and limitations](docs/v2-research.md).

En lokal researchplattform för att utvärdera och prioritera produktidéer inom
e-commerce. V1 innehåller **en Product Research Analyst**. Appen startar direkt
med 12 tydligt märkta demoprodukter och behöver ingen API-nyckel för att fungera.

## Funktioner i V1

- **Dashboard:** analysmått, rankad tabell, produktkort och detaljer.
- **Research:** sök kategori/sökterm i lokala produkter eller lägg till en egen
  kandidat med kostnad, pris och poängantaganden. Tom sökning visar alla.
- **Analys:** efterfrågan, konkurrens, trend, marknadsföring, risker, målgrupp,
  prishypoteser och konkreta nästa researchsteg.
- **Transparent scoring:** totalpoäng 0–100, marginal och rekommendation beräknas
  deterministiskt. Detaljvyn visar varje faktors bidrag.
- **Sortering/filter:** AI Score, Margin, Demand, Competition, Trend samt filter
  för kategori, minsta poäng, minsta marginal och rekommendation.
- **Saved Products:** sparade analyssnapshots och manuella kandidater ligger i
  SQLite och finns kvar efter omstart. Samma namn/kategori ger en uppdatering,
  aldrig en ny dubblett. Uppdatera en sparad analys uttryckligen med knappen.
- **Settings:** välj demo eller OpenAI när en nyckel finns. Demo är standard.

Dashboard-måtten avser den senaste analysen i aktuell session; antalet sparade
produkter kommer från databasen. Att ta bort en sparad produkt tar bort
shortlistens snapshot, inte en manuellt inmatad kandidat.

## Installation

Kräver **Python 3.12 eller senare**. Kör följande i projektmappen.
Den lokala `.venv` som redan skapats kan användas direkt på den här datorn.

### Windows / PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Om din Python-installation använder `py`, använd `py -3.12 -m venv .venv`.
Aktivering är valfri: `.\.venv\Scripts\Activate.ps1`. Kommandona här fungerar
utan aktivering och behöver ingen ändring av PowerShells execution policy.

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

## Konfiguration

`.env` kan innehålla:

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
OPENAI_RESEARCH_MODEL=gpt-4.1-mini
DATABASE_PATH=data/commerce.db
```

Lämna nyckeln tom för demo. Utan `.env` används samma säkra standardvärden.
Miljövariabler har företräde framför `.env`. Relativa databasvägar utgår alltid
från projektmappen, även om appen startas från en annan arbetsmapp.

För OpenAI: skriv in din egen nyckel i `.env`, ladda om appen, öppna **Settings**
och stäng av demoläget. Nästa researchinlämning använder OpenAI. Ändringen
analyserar inte tidigare resultat automatiskt. Varje matchande produkt skickas
till API:t och kan medföra kostnad; högst 20 kandidater analyseras per sökning.
Modellen måste vara tillgänglig för ditt API-konto och stödja Structured Outputs.

API-nyckeln är aldrig hårdkodad, visas inte i UI och `.env` är Git-ignorerad.
API-fel, timeout, refusal eller ogiltig output ger en **synligt märkt demo-fallback**.
SDK-anrop har 20 sekunders timeout och gör inga automatiska omförsök. Den
vanliga navigeringen, sparningen och uppstarten gör inga API-anrop.

## Kör appen

Windows:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

macOS/Linux:

```bash
.venv/bin/python -m streamlit run app.py
```

Öppna [http://localhost:8501](http://localhost:8501). Servern lyssnar endast på
den lokala datorn. Stoppa med `Ctrl+C`; starta igen med samma kommando.
Om porten används: lägg till `--server.port 8502` och öppna den porten.
Windows har även hjälpskriptet `scripts/start.ps1 -Port 8501` om skriptkörning
redan är tillåten i din miljö.

### Prova hela flödet

1. Starta appen och se demoprodukterna på Dashboard.
2. Öppna Research, sök `pet accessories` och klicka **Find / Analyze Products**.
3. Öppna ett produktkort med **View details**, eller använd detaljväljaren.
4. Läs analysen, **Data & assumptions** och **Score calculation**.
5. Klicka **Save product** och öppna **Saved Products**.
6. Stoppa appen och starta den igen. Produkten finns kvar i Saved Products.
7. Ta bort den med **Remove saved product** när den inte längre hör till shortlistan.

## Hur poängen räknas

```text
gross_margin = (selling_price - product_cost) / selling_price × 100
margin_score = clamp(gross_margin / 10, 0, 10)

overall_score = 10 × (
    0.25 × demand
  + 0.25 × margin_score
  + 0.20 × trend
  + 0.15 × (10 - competition)
  + 0.15 × marketing
)
```

Totalpoängen avrundas till en decimal. Demand, competition, trend och marketing
är bedömningar mellan 0 och 10. Lägre konkurrens ger högre totalpoäng.
**Profit potential** är samma deterministiska marginalpoäng; det är inte
beräknad nettovinst. Negativa marginaler visas, men ger marginalpoängen noll.
Marginalen använder full precision i beräkningen och en decimal vid visning.

Rekommendation: **Strong candidate** vid minst 75, **Worth investigating** vid
minst 55, annars **Weak candidate**. Poängen är ett prioriteringsstöd och ingen
sannolikhet för framgång. Produktmarginalen exkluderar frakt, annonser, avgifter,
skatter och returer.

## Data och trovärdighet

- **Verified data:** endast fakta och källreferenser från dataproviders.
  V1:s lokala demo/manuella produkter har inga verifierade marknadsfakta.
- **Estimated data:** inmatade kostnader, priser och score-antaganden.
- **AI judgement / demo judgement:** poängbedömningar, målgrupp,
  marknadsföringsidéer, prishypoteser, risker och nästa steg.

Demoanalysen använder input-antaganden deterministiskt; inga externa fakta
hämtas. OpenAI-analysen använder SDK:ts `responses.parse` med Pydantic enligt
[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
Modellen får inte skriva över verifierade källfakta eller sätta totalpoäng.
Strukturerad output validerar format och intervall, men garanterar inte att
textbedömningen är sann. Alla slutsatser behöver därför research med källor.

## Projektstruktur

```text
app.py                         Streamlit-startpunkt
src/
  config.py                    .env och inställningar
  schemas/product.py           Validerade produkter, analyser och score-output
  agents/product_research_agent.py   En researchanalyst, demo/OpenAI
  sources/local.py             Lokala seeddata och ProductSource-protokoll
  services/scoring.py          Marginal, vikter, totalpoäng och rekommendation
  services/product_service.py  Sökning, source-sammansättning, sortering/filter
  database/database.py        SQLite, kandidater och sparade snapshots
  ui/                         Dashboard, research, produktvyer och settings
data/demo_products.json       12 exempelprodukter från sex kategorier
data/commerce.db              Skapas vid första start; Git-ignorerad
tests/                        Enhets-, databas-, SDK- och AppTest-tester
scripts/start.ps1             Windows-startskript
docs/                         Design, plan och verifieringsresultat
requirements.txt              Direkta beroenden med kompatibla versionsintervall
requirements-lock.txt         Exakta versioner från den verifierade miljön
.env.example                  Konfigurationsmall
```

## Tester

Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

macOS/Linux: `.venv/bin/python -m pytest`.
Tester använder temporära databaser och simulerad HTTP-transport för OpenAI,
så de behöver ingen nyckel, gör inga betalda API-anrop och ändrar inte dina
sparade produkter. De täcker score/marginal, invalida värden, dubbletter,
persistens, sortering/filter, demo, structured output/fallback och hela
Streamlit-flödet inklusive ny appsession med sparade produkter.

För att återskapa exakt verifierade beroenden:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

Valfri kodkontroll: installera `ruff` och kör `ruff check .` och
`ruff format --check .`. Se [verifieringsrapporten](docs/verification.md) för
de faktiskt körda kontrollerna och kända begränsningarna.

## Begränsningar och nästa steg

V1 söker bara lokala produkter; den upptäcker inte nya marknadsprodukter från
internet. All seeddata är påhittad demo/estimated. Verklig OpenAI-responskvalitet
kräver en separat körning med API-nyckel. Appen är en lokal enanvändarapp utan
autentisering. Endast manuella kandidater och uttryckligen sparade analyser
bevaras; övriga researchresultat och filter hör till webbläsarsessionen.

Nästa rekommenderade steg är **en riktig datakälla med daterade källreferenser**.
Implementera `ProductSource.search(query) -> list[Product]` och injicera den i
`ResearchService(sources=[...])`. Låt källan tillhandahålla verifierbara fakta i
`Product.evidence`; separera observerade data från estimat innan agenten bedömer
dem. Lägg därefter till landed cost, frakt/returer och annonskostnader innan
poängen används för investeringsbeslut.

Shopify, ordering, fulfillment, annonseringsautomation, support, betalningar,
browser automation och fleragentsorkestrering ingår inte i V1.

V2 still excludes those automation workflows. It searches current public web
information only after an explicit **Research product** action with demo mode
disabled. Research snapshots, unique sources, attempts and economics are stored
in additive version-2 SQLite tables; existing V1 saved-product data is retained.
