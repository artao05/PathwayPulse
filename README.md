# PathwayPulse

**Autonomous Biotech Arbitrage Engine** — detects cross-indication drug repurposing signals in real time.

PathwayPulse monitors when a biological pathway proven in one disease (e.g., oncology) is quietly being applied to a completely different disease (e.g., autoimmune) — before the broader market notices. It ingests preprints, peer-reviewed literature, community commentary, conference abstracts, and clinical trial data; grounds detected signals with biological and pharmacology databases; then renders the results as a live arbitrage graph with a written intelligence report.

Built for the [Web Data UNLOCKED Hackathon](https://brightdata.com).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Ingestion Swarm                          │
│                                                                 │
│  bioRxiv API ─────────────────────────────────────────────┐     │
│  medRxiv API ─────────────────────────────────────────────┤     │
│  Reddit RSS (5 subs) ─────────────────────────────────────┤     │
│  PubMed E-utilities ─────────────────────────────────────┤     │
│  OpenAlex citation metadata ─────────────────────────────┤     │
│  ChemRxiv API (opt) ─────────────────────────────────────┤     │
│  Grok xAI x_search (opt) ────────────────────────────────┤     │
│  ClinicalTrials.gov API v2 ──────────────────────────────┤     │
│  BrightData Scraping Browser ─► ACR abstracts ──────────────┘     │
└──────────────────────────────┬──────────────────────────────────┘
                               │ up to 600 raw records
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Synthesizer (DeepSeek-V3)                     │
│  asyncio.gather — up to 10 concurrent requests                  │
│  Pydantic-enforced CrossPollinationEvent output                 │
│  { pathway, from_disease, to_disease, confidence, evidence }   │
└──────────────────────────────┬──────────────────────────────────┘
                               │ structured events + catalyst list
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│             Validation + Enrichment Layer                       │
│  OpenTargets target-disease evidence scores                     │
│  Reactome pathway enrichment                                    │
│  Ensembl gene resolution + UniProt protein annotations          │
│  ChEMBL mechanisms / IC50 / Ki + openFDA safety context         │
└──────────────────────────────┬──────────────────────────────────┘
                               │ grounded events + drug profiles
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Executioner (GPT-4o)                           │
│  Bear / Bull / Neutral verdict + immunological soundness eval   │
│  Catalyst Calendar section (overdue + imminent readouts)        │
│  Risk factors + company / trial watch list                      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Streamlit Dashboard                           │
│  Interactive node graph  │  Intelligence Report                 │
│  Catalyst Calendar       │  Validation + pharmacology panels    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
PathwayPulse/
├── app.py                   # Streamlit dashboard — node graph, report, catalyst calendar
├── ai_orchestrator.py       # AI pipeline + validation / pharmacology enrichment
├── swarm_ingestion.py       # All ingestion agents — preprints, Reddit, BrightData, CT API
├── test_connections.py      # API smoke-tests — run before first use
├── requirements.txt
├── .env.template            # Copy → .env, fill in keys
├── kol_handles.json         # Default X/Twitter KOL handles (overridable in sidebar)
└── reddit_subreddits.json   # Default subreddits (overridable in sidebar)
```

---

## Quickstart

### 1. Prerequisites

- Python 3.9+
- [AI/ML API](https://aimlapi.com) key (routes to DeepSeek-V3)
- [OpenAI](https://platform.openai.com) API key (GPT-4o)
- *(Optional)* [Bright Data](https://brightdata.com) Scraping Browser zone for ACR conference abstracts
- *(Optional)* [xAI API](https://console.x.ai) key for KOL X/Twitter ingestion via Grok
- *(Optional)* NCBI/OpenAlex/openFDA keys for higher rate limits and polite API pools

### 2. Clone and install

```bash
git clone https://github.com/artao05/PathwayPulse.git
cd PathwayPulse

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium      # BrightData Scraping Browser uses Playwright CDP
```

### 3. Configure API keys

```bash
cp .env.template .env
```

| Key | Where to find it |
|-----|-----------------|
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `AIMLAPI_KEY` | [aimlapi.com](https://aimlapi.com) → API Keys |
| `NCBI_API_KEY` | NCBI account *(optional — raises PubMed rate limits)* |
| `USER_EMAIL` | Your email *(optional — NCBI/OpenAlex polite pool)* |
| `OPENALEX_API_KEY` | [openalex.org](https://openalex.org) *(optional — citations)* |
| `FDA_API_KEY` | [open.fda.gov](https://open.fda.gov/apis/authentication/) *(optional — raises openFDA limits)* |
| `XAI_API_KEY` | [console.x.ai](https://console.x.ai) → API Keys *(optional — enables KOL X ingestion)* |
| `BRIGHTDATA_BROWSER_AUTH` | Bright Data dashboard → Scraping Browser zone → Access Parameters → `username:password` *(optional)* |

### 4. Validate connections

```bash
python test_connections.py
```

Required checks must show `✓ PASS` before proceeding. Optional sources may warn if their keys are not configured:

```
✓ PASS  aimlapi (required)
✓ PASS  reddit scrape (required)
✓ PASS  preprints (required)
⚠ WARN  brightdata (optional)
⚠ WARN  twitter (optional)
```

### 5. Run the dashboard

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501).

---

## Deploy for Hackathon Judges (Streamlit Community Cloud)

PathwayPulse is ready to deploy on **[Streamlit Community Cloud](https://share.streamlit.io)** — free, public URL, no server management.

**Quick steps:**

1. Push this repo to GitHub (`artao05/PathwayPulse`)
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app** → select repo, branch `main`, main file `app.py`
3. **Settings → Secrets** — paste keys from [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example):
   - Required: `OPENAI_API_KEY`, `AIMLAPI_KEY`
   - Optional: `XAI_API_KEY`, `BRIGHTDATA_BROWSER_AUTH`
4. Share the public URL with judges (e.g. `https://pathwaypulse.streamlit.app`)

Full instructions: **[DEPLOY.md](DEPLOY.md)**

**What judges get without BrightData:** preprints, PubMed, Reddit, ClinicalTrials.gov API v2, Catalyst Calendar, validation/enrichment layers, AI synthesis, node graph, and intelligence report (~2–4 min per run).

**With BrightData secret:** ACR conference abstracts also enabled (~4–5 min per run).

---

## How BrightData Is Used

BrightData's **Scraping Browser** (Playwright over CDP WebSocket) is optional and used only for conference abstract portals that benefit from JavaScript rendering and bot-evasion:

### 1. ACR Conference Abstracts (`acrabstracts.org`)

The American College of Rheumatology abstract portal returns server-rendered HTML but aggressively rate-limits unauthenticated scrapers. BrightData handles bot evasion and IP rotation.

**Scraping strategy:**
1. Navigate to `https://acrabstracts.org/?s={query}` via BrightData WebSocket
2. Extract all `/abstract/SLUG` links from the results page (up to 3 pages, 15 links per page)
3. Visit each abstract detail page; extract title (`.entry-title`) and body (`.entry-content`)
4. Returns up to 45 structured records per run

**Access tier:** Green — `acrabstracts.org/robots.txt` is fully open (`Disallow:` nothing).

### ClinicalTrials.gov and Catalyst Calendar — API v2

```
ClinicalTrials.gov API v2
  └─► query.term / query.intr / query.spons
        └─► NCT IDs + structured study modules
              └─► startDateStruct, primaryCompletionDateStruct,
                  status, phase, sponsor, interventions
                    └─► derive days_until_readout, bucket
                          (overdue / imminent / near / upcoming / reported)
```

ClinicalTrials.gov no longer uses BrightData or Playwright. The app queries the free API v2 directly and returns `[]` gracefully if the endpoint is unavailable.

### Connection pattern

```python
ws_url = f"wss://{BRIGHTDATA_BROWSER_AUTH}@brd.superproxy.io:9222"

async with async_playwright() as p:
    browser = await asyncio.wait_for(
        p.chromium.connect_over_cdp(ws_url), timeout=60
    )
    page = await browser.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
```

---

## Data Sources

| Source | Access method | Auth required | Notes |
|--------|--------------|---------------|-------|
| bioRxiv | REST API (`api.biorxiv.org`) | None | Paginated JSON; up to 300 records per run |
| medRxiv | REST API (`api.biorxiv.org`) | None | Same endpoint, `server=medrxiv` |
| PubMed | NCBI E-utilities | Optional `NCBI_API_KEY` | Peer-reviewed abstracts for signal maturity |
| OpenAlex | REST API (`api.openalex.org`) | Optional `OPENALEX_API_KEY` | Citation counts and journal-version metadata for DOI-bearing preprints |
| Reddit | Atom RSS feed | None | `reddit.com/r/{sub}/new.rss` — OAuth not required |
| X / Twitter | Grok `x_search` tool (xAI API) | `XAI_API_KEY` | ~$0.005/run; enter handles in sidebar |
| ChemRxiv | REST API (`chemrxiv.org`) | None | Pharmacology/biochemistry filter |
| ClinicalTrials.gov (text) | REST API v2 (`clinicaltrials.gov/api/v2/studies`) | None | Free structured JSON; no BrightData or Playwright needed |
| ClinicalTrials.gov (Catalyst Calendar) | CT API v2 | None | `startDateStruct`, `primaryCompletionDateStruct`, `ACTUAL` vs `ESTIMATED` type |
| ACR Abstracts (`acrabstracts.org`) | BrightData Scraping Browser | `BRIGHTDATA_BROWSER_AUTH` | Green tier — open `robots.txt`. Up to 45 abstracts per run |
| ASCO Abstracts (`meetings.asco.org`) | BrightData Scraping Browser | `BRIGHTDATA_BROWSER_AUTH` | Red tier — ASCO is a non-profit; BrightData may apply NGO classification. Returns `[]` gracefully if blocked. Submit KYC at brightdata.com to unlock |

## Validation & Enrichment Sources

| Source | Access method | Auth required | Used for |
|--------|--------------|---------------|----------|
| OpenTargets | GraphQL API | None | Target-disease association scores for detected gene/indication pairs |
| Reactome | AnalysisService API | None | Pathway enrichment over resolved target genes |
| Ensembl | REST API | None | Gene symbol / Ensembl ID resolution and genomic metadata |
| UniProt | REST API | None | Reviewed human protein names, function notes, locations, GO terms |
| ChEMBL | REST API | None | Drug mechanism of action, indications, representative IC50/Ki rows |
| openFDA | REST API | Optional `FDA_API_KEY` | FAERS adverse-event counts, top reactions, FDA label warnings |

> **Reddit:** Reddit's JSON API requires OAuth and Bright Data respects Reddit's `robots.txt`. The Atom RSS feed is explicitly permitted and is the reliable zero-friction path.

> **X/Twitter:** The free Twitter API is write-only. Bright Data's Scraping Browser cannot access X due to `robots.txt` compliance. PathwayPulse uses the Grok xAI Responses API (`x_search` tool) as the only reliable free-access path.

> **ClinicalTrials.gov:** The Catalyst Calendar uses API v2 directly for authoritative structured date fields; no BrightData access is required.

> **Conference abstracts:** BrightData may classify non-profit/NGO domains as restricted. ACR (`acrabstracts.org`) is a private entity with an open `robots.txt` — safe target. ASCO (`meetings.asco.org`) is a non-profit and may trigger an NGO block; the scraper catches `proxy_error` and returns `[]` without crashing.

---

## AI Pipeline

### Synthesizer — DeepSeek-V3 via AI/ML API

- Processes records concurrently in batches of up to 10
- Prompt instructs extraction of: `pathway`, `from_disease`, `to_disease`, `confidence` (0–1), `source_evidence`, `source_label`
- Returns `CrossPollinationEvent` Pydantic objects via `response_format={"type": "json_object"}`
- Failures are logged and skipped — the pipeline never halts on a bad record
- Cost: ~$0.001 per record

### Executioner — GPT-4o via OpenAI

- Called once per run after all events and catalyst data are collected
- System prompt defines a structured report: verdict, immunological soundness, ranked signals, catalyst calendar, risk factors, watch list
- Biological validation, pharmacology profiles, and catalyst data are injected into the user prompt for context
- Cost: ~$0.01–0.05 per report

### Biological validation

`validate_events()` runs between the Synthesizer and Executioner:

- Resolves target candidates with OpenTargets and scores target-disease evidence against the novel indication
- Runs Reactome enrichment over resolved genes
- Adds Ensembl gene summaries and UniProt protein annotations to each event
- Returns partial notes instead of raising when an external source cannot resolve a target

### Pharmacology enrichment

`enrich_pharmacology()` builds per-drug profiles from the explicit drug filter, ClinicalTrials interventions, and obvious drug suffixes in event evidence:

- ChEMBL molecule resolution, mechanisms of action, indications, and representative IC50/Ki rows
- openFDA FAERS totals, serious event counts, top MedDRA reactions, and selected label warnings
- Profiles are passed to the Executioner so the Risk Factors section can cite factual pharmacology/safety context

### Catalyst Calendar derivation

```python
days = (primary_completion_date - today).days
bucket = (
    "overdue"   if days < 0  and not results_posted else
    "imminent"  if days < 90  else
    "near"      if days < 180 else
    "upcoming"
)
```

Color coding: 🔴 Overdue · 🟠 Imminent (<90d) · 🟡 Near (90–180d) · 🔵 Upcoming (>180d) · ✅ Reported

### Budget protection

- `@st.cache_data(ttl=3600)` on all ingestion and catalyst functions — dashboard interactions never re-trigger APIs
- `asyncio.gather(*tasks, return_exceptions=True)` — one bad record never kills the batch
- bioRxiv/medRxiv capped at 300 records per server per run

---

## Dashboard Controls

| Control | Description |
|---------|-------------|
| **Biological Pathway** | Pathway to track. Try `IL-6 signaling`, `GLP-1 receptor`, `JAK-STAT`, `mTOR`, `PD-1/PD-L1`. |
| **Drug / Intervention** | Optional. Narrows ClinicalTrials searches to a specific drug (e.g. `tocilizumab`). |
| **Sponsor / Company** | Optional. Filters ClinicalTrials results to a specific lead sponsor (e.g. `Roche`). |
| **Days of preprint history** | How far back to pull bioRxiv/medRxiv. 3–7 days default; 14 for broad coverage. |
| **Include PubMed** | Adds recent peer-reviewed abstracts via NCBI E-utilities. |
| **Enrich preprints with OpenAlex citations** | Adds citation counts and published-journal metadata where available. |
| **Run biological validation** | Adds OpenTargets, Reactome, Ensembl, and UniProt grounding to detected events. |
| **Run pharmacology enrichment** | Adds ChEMBL and openFDA drug context for detected drugs/interventions. |
| **Include ChemRxiv** | Adds preclinical pharmacology papers. |
| **Include ClinicalTrials.gov text records** | Scrapes active/recruiting trial summaries; feeds the Synthesizer. |
| **Show Catalyst Calendar** | Upcoming and overdue trial readouts with dates and days-until badges. Works via API v2 without BrightData. |
| **Conference abstracts** | ACR (green tier) and/or ASCO (NGO-risk tier). Requires `BRIGHTDATA_BROWSER_AUTH`. |
| **Reddit Subreddits** | Subreddits to monitor via RSS. Defaults from `reddit_subreddits.json`. |
| **X / Twitter KOL Handles** | Public X handles. Grok searches their recent posts. Requires `XAI_API_KEY`. |
| **Report model** | `gpt-4o` (fast) or `o1` (deeper scientific reasoning). |
| **Run Analysis** | Cold run: 3–5 min. Warm cache: ~2 min (synthesis only). |
| **Clear Cache** | Forces fresh data pull and re-analysis. |

### Reading the Arbitrage Matrix

- **Central node** — the biological pathway
- **Child nodes** — novel therapeutic indications where the pathway was detected
- **Crimson animated edges** — high-confidence signals (≥50%)
- **Gray edges** — weak or speculative signals (<50%)
- **Intelligence Report** — Bear / Bull / Neutral verdict with immunological soundness, ranked signals, Catalyst Calendar summary, risk factors, watch list
- **📅 Catalyst Calendar** — color-coded trial readout timeline; each row shows date, days-until badge, phase, sponsor, drug names, and CT.gov link
- **🧬 Biological Validation** — OpenTargets scores, Reactome matches, Ensembl genes, and UniProt proteins for resolved targets
- **💊 Pharmacology & Safety** — ChEMBL mechanisms/activity plus openFDA event and label context
- **📋 Raw Signal Data** — every detected event with link to source
- **🗂 Ingested Sources** — all raw records grouped by source type

---

## Performance

Typical run on `IL-6 signaling` with ACR abstracts enabled:

| Stage | Records | Duration |
|-------|---------|----------|
| bioRxiv + medRxiv | 60 | ~3s |
| PubMed | up to 50 | ~1–3s |
| Reddit (5 subs) | 250 | ~2s |
| ACR abstracts via BrightData | 45 | ~3 min (3 pages) |
| ClinicalTrials API v2 | 50 | ~1s |
| DeepSeek-V3 synthesis (355 records) | 355 | ~90s |
| Validation / pharmacology enrichment | detected signals / drugs | ~10–45s |
| GPT-4o Intelligence Report | — | ~15s |
| **Total (cold)** | **355** | **~4–5 min** |
| **Total (warm cache)** | **355** | **~2 min** |

---

## Running Tests

```bash
# Validate all API connections before first use
python test_connections.py

# Run the AI pipeline with sample data
python ai_orchestrator.py

# Exercise ingestion agents individually
python swarm_ingestion.py
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `streamlit` | Dashboard framework |
| `streamlit-flow-component` | Interactive node graph |
| `openai` | SDK for OpenAI (GPT-4o) and AI/ML API (DeepSeek-V3) via `base_url` |
| `pydantic` | Structured output schema enforcement |
| `playwright` | Headless browser automation over BrightData CDP WebSocket |
| `requests` | HTTP calls to ingestion, validation, pharmacology, and annotation APIs |
| `tenacity` | Exponential backoff retry for API calls |
| `python-dotenv` | `.env` file loading |

---

## Future Directions

**Expand data sources**
- SEC EDGAR 8-K/10-K filings — companies bury cross-indication pivots in footnotes months before press releases
- Additional conference portals — EASD (diabetes), ESMO (oncology) as BrightData targets once robots.txt access is confirmed

**Signal tracking over time**
Store `CrossPollinationEvent` history in SQLite. Add a "Signal Momentum" chart showing confidence score week-over-week — is a thesis strengthening or fading?

**Named entity extraction**
Add richer NER over `source_evidence` to auto-populate company names, trial IDs, and ambiguous drug/gene mentions beyond the current suffix and database-resolution heuristics.

**Ticker mapping**
Map novel indications to publicly traded companies via a curated `indication_to_tickers.json` lookup, turning biological signals directly into equity watch lists.

**RAG memory layer**
Store past events in a vector database (ChromaDB). On new runs, retrieve the most similar past signals and inject historical context into the Executioner prompt.

**Scheduled alerts**
Run nightly via `cron` or GitHub Actions; push a Slack/email summary when a new high-confidence signal appears that wasn't in the prior run.

---

## License

MIT

---

## Acknowledgments

Built with [Bright Data](https://brightdata.com), [AI/ML API](https://aimlapi.com), [OpenAI](https://openai.com), [xAI Grok](https://x.ai), [bioRxiv](https://biorxiv.org), [medRxiv](https://medrxiv.org), [PubMed](https://pubmed.ncbi.nlm.nih.gov), [OpenAlex](https://openalex.org), [OpenTargets](https://platform.opentargets.org), [Reactome](https://reactome.org), [Ensembl](https://www.ensembl.org), [UniProt](https://www.uniprot.org), [ChEMBL](https://www.ebi.ac.uk/chembl), [openFDA](https://open.fda.gov), and [Streamlit](https://streamlit.io).
