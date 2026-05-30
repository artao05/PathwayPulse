# PathwayPulse

**Autonomous Biotech Arbitrage Engine** — detects cross-indication drug repurposing signals in real time.

PathwayPulse monitors when a biological pathway proven in one disease (e.g., oncology) is quietly being applied to a completely different disease (e.g., autoimmune) — before the broader market notices. It ingests preprints, community commentary, conference abstracts, and clinical trial data, runs them through a two-stage AI pipeline, and renders the results as a live arbitrage graph with a written intelligence report.

Built for the [Web Data UNLOCKED Hackathon](https://brightdata.com).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Ingestion Swarm                          │
│                                                                 │
│  bioRxiv API ──────────────────────────────────────────────┐   │
│  medRxiv API ──────────────────────────────────────────────┤   │
│  Reddit RSS (5 subs) ──────────────────────────────────────┤   │
│  ChemRxiv API (opt) ───────────────────────────────────────┤   │
│  Grok xAI x_search (opt) ─────────────────────────────────┤   │
│  BrightData Scraping Browser ─► ACR abstracts ────────────┤   │
│  BrightData Scraping Browser ─► ClinicalTrials.gov ───────┤   │
│    └─► CT API v2 enrichment (dates, phase, sponsor) ──────┘   │
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
│  Catalyst Calendar       │  Raw signal explorer                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
PathwayPulse/
├── app.py                   # Streamlit dashboard — node graph, report, catalyst calendar
├── ai_orchestrator.py       # Synthesizer (DeepSeek-V3) + Executioner (GPT-4o) pipeline
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
- [Bright Data](https://brightdata.com) account with a **Scraping Browser** zone
- [AI/ML API](https://aimlapi.com) key (routes to DeepSeek-V3)
- [OpenAI](https://platform.openai.com) API key (GPT-4o)
- *(Optional)* [xAI API](https://console.x.ai) key for KOL X/Twitter ingestion via Grok

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
| `BRIGHTDATA_BROWSER_AUTH` | Bright Data dashboard → Scraping Browser zone → Access Parameters → `username:password` |
| `XAI_API_KEY` | [console.x.ai](https://console.x.ai) → API Keys *(optional — enables KOL X ingestion)* |

### 4. Validate connections

```bash
python test_connections.py
```

All four required checks must show `✓ PASS` before proceeding:

```
✓ PASS  aimlapi (required)
✓ PASS  brightdata (required)
✓ PASS  reddit scrape (required)
✓ PASS  preprints (required)
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

**What judges get without BrightData:** preprints, Reddit, Catalyst Calendar (API v2), AI synthesis, node graph, and intelligence report (~2–4 min per run).

**With BrightData secret:** ACR conference abstracts also enabled (~4–5 min per run).

---

## How BrightData Is Used

BrightData's **Scraping Browser** (Playwright over CDP WebSocket) is used for two targets that require JavaScript rendering and bot-evasion:

### 1. ACR Conference Abstracts (`acrabstracts.org`)

The American College of Rheumatology abstract portal returns server-rendered HTML but aggressively rate-limits unauthenticated scrapers. BrightData handles bot evasion and IP rotation.

**Scraping strategy:**
1. Navigate to `https://acrabstracts.org/?s={query}` via BrightData WebSocket
2. Extract all `/abstract/SLUG` links from the results page (up to 3 pages, 15 links per page)
3. Visit each abstract detail page; extract title (`.entry-title`) and body (`.entry-content`)
4. Returns up to 45 structured records per run

**Access tier:** Green — `acrabstracts.org/robots.txt` is fully open (`Disallow:` nothing).

### 2. ClinicalTrials.gov Text Records (`clinicaltrials.gov`)

The ClinicalTrials.gov search interface is a JavaScript-heavy Angular SPA. BrightData renders it and extracts NCT IDs from the result cards.

**Note:** BrightData classifies `.gov` domains as Government and blocks them by default. The scraper detects this and falls back automatically to the free ClinicalTrials.gov **API v2** (`clinicaltrials.gov/api/v2/studies`), which requires no authentication and returns the same structured data.

### Catalyst Calendar — Hybrid BrightData + API v2

```
BrightData Scraping Browser
  └─► NCT IDs from search result cards
        └─► CT API v2 enrichment per NCT ID
              └─► startDateStruct, primaryCompletionDateStruct,
                  status, phase, sponsor, interventions
                    └─► derive days_until_readout, bucket
                          (overdue / imminent / near / upcoming / reported)
```

If BrightData is unavailable or blocked, the pipeline falls back to a direct API v2 keyword query, ensuring the Catalyst Calendar always populates.

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
| Reddit | Atom RSS feed | None | `reddit.com/r/{sub}/new.rss` — OAuth not required |
| X / Twitter | Grok `x_search` tool (xAI API) | `XAI_API_KEY` | ~$0.005/run; enter handles in sidebar |
| ChemRxiv | REST API (`chemrxiv.org`) | None | Pharmacology/biochemistry filter |
| ClinicalTrials.gov (text) | BrightData Scraping Browser → API v2 fallback | `BRIGHTDATA_BROWSER_AUTH` | BrightData blocked by `.gov` policy; API v2 fallback activates automatically |
| ClinicalTrials.gov (Catalyst Calendar) | CT API v2 | None | `startDateStruct`, `primaryCompletionDateStruct`, `ACTUAL` vs `ESTIMATED` type |
| ACR Abstracts (`acrabstracts.org`) | BrightData Scraping Browser | `BRIGHTDATA_BROWSER_AUTH` | Green tier — open `robots.txt`. Up to 45 abstracts per run |
| ASCO Abstracts (`meetings.asco.org`) | BrightData Scraping Browser | `BRIGHTDATA_BROWSER_AUTH` | Red tier — ASCO is a non-profit; BrightData may apply NGO classification. Returns `[]` gracefully if blocked. Submit KYC at brightdata.com to unlock |

> **Reddit:** Reddit's JSON API requires OAuth and Bright Data respects Reddit's `robots.txt`. The Atom RSS feed is explicitly permitted and is the reliable zero-friction path.

> **X/Twitter:** The free Twitter API is write-only. Bright Data's Scraping Browser cannot access X due to `robots.txt` compliance. PathwayPulse uses the Grok xAI Responses API (`x_search` tool) as the only reliable free-access path.

> **ClinicalTrials.gov:** `.gov` domains are blocked by BrightData's Acceptable Use Policy by default. The Catalyst Calendar uses a hybrid strategy: BrightData for NCT ID discovery on the SPA, then CT API v2 for authoritative structured date fields that the Scraping Browser card text doesn't expose.

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
- System prompt defines a structured 4-part report: verdict, immunological soundness, ranked signals, catalyst calendar, risk factors, watch list
- Catalyst data (overdue/imminent readouts) is injected into the user prompt for context
- Cost: ~$0.01–0.05 per report

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
- **📋 Raw Signal Data** — every detected event with link to source
- **🗂 Ingested Sources** — all raw records grouped by source type

---

## Performance

Typical run on `IL-6 signaling` with ACR abstracts enabled:

| Stage | Records | Duration |
|-------|---------|----------|
| bioRxiv + medRxiv | 60 | ~3s |
| Reddit (5 subs) | 250 | ~2s |
| ACR abstracts via BrightData | 45 | ~3 min (3 pages) |
| ClinicalTrials API v2 fallback | 50 | ~1s |
| DeepSeek-V3 synthesis (355 records) | 355 | ~90s |
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
| `requests` | HTTP calls to preprint APIs and Reddit RSS |
| `tenacity` | Exponential backoff retry for API calls |
| `python-dotenv` | `.env` file loading |

---

## Future Directions

**Expand data sources**
- SEC EDGAR 8-K/10-K filings — companies bury cross-indication pivots in footnotes months before press releases
- PubMed/NCBI Entrez — peer-reviewed publications add signal maturity context layered on top of preprints
- Additional conference portals — EASD (diabetes), ESMO (oncology) as BrightData targets once robots.txt access is confirmed

**Signal tracking over time**
Store `CrossPollinationEvent` history in SQLite. Add a "Signal Momentum" chart showing confidence score week-over-week — is a thesis strengthening or fading?

**Named entity extraction**
Add NER over `source_evidence` to auto-populate drug names, company names, trial IDs, and gene targets rather than relying on GPT-4o to infer them.

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

Built with [Bright Data](https://brightdata.com), [AI/ML API](https://aimlapi.com), [OpenAI](https://openai.com), [xAI Grok](https://x.ai), [bioRxiv](https://biorxiv.org), [medRxiv](https://medrxiv.org), and [Streamlit](https://streamlit.io).
