# AI Commerce Agent

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
