# PathwayPulse

**Autonomous Biotech Arbitrage Engine**

PathwayPulse detects when a biological pathway or treatment mechanism proven in one disease area (e.g., oncology) is quietly being applied to a completely different disease (e.g., autoimmune conditions) — before the broader market notices. It ingests scientific preprints, Reddit biotech commentary, and optional preclinical chemistry papers, runs them through a two-stage AI pipeline, and renders the results as a live node graph with a written intelligence report.

Built for the [Web Data UNLOCKED Hackathon](https://brightdata.com).

---

## How It Works

```
bioRxiv ──┐
medRxiv ──┼──► Synthesizer (DeepSeek-V3) ──► CrossPollinationEvents ──► Node Graph
Reddit  ──┘         │                                    │
ChemRxiv (opt) ─────┘              Executioner (GPT-4o) ──► Bear/Bull/Neutral Report
```

1. **Ingest** — Four agents pull data in parallel: bioRxiv + medRxiv preprints (up to 600 records), Reddit r/biotech via RSS feed, optional ChemRxiv pharmacology papers.
2. **Synthesize** — DeepSeek-V3 (via AI/ML API) triages every record asynchronously and extracts structured `CrossPollinationEvent` objects: what pathway, from which disease, into which new disease, with what confidence.
3. **Execute** — GPT-4o reads all detected events and writes a Bear / Bull / Neutral arbitrage intelligence report evaluating immunological plausibility, signal quality, and risk factors.
4. **Visualize** — A Streamlit dashboard renders the results as a dynamic node graph. High-confidence signals pulse with animated crimson edges; weak signals appear muted.

---

## Screenshots

> Run `streamlit run app.py`, enter a pathway (e.g. `GLP-1 receptor`), and click **Run Analysis**.

The Arbitrage Matrix node graph populates with child nodes for each novel indication detected, and the Intelligence Report appears alongside it.

---

## Project Structure

```
PathwayPulse/
├── app.py                 # Streamlit dashboard (node graph + report)
├── ai_orchestrator.py     # Dual-model AI pipeline (Synthesizer + Executioner)
├── swarm_ingestion.py     # Four data ingestion agents
├── test_connections.py    # API smoke-tests — run this first
├── requirements.txt       # Python dependencies
├── .env.template          # Copy to .env and fill in your API keys
└── .gitignore
```

---

## Quickstart

### 1. Prerequisites

- Python 3.9+
- A [Bright Data](https://brightdata.com) account with a **Scraping Browser** zone
- An [AI/ML API](https://aimlapi.com) key (routes to DeepSeek-V3)
- An [OpenAI](https://platform.openai.com) API key (GPT-4o)

### 2. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/PathwayPulse.git
cd PathwayPulse

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium
```

### 3. Configure API keys

```bash
cp .env.template .env
```

Open `.env` and fill in your values:

| Key | Where to find it |
|-----|-----------------|
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `AIMLAPI_KEY` | [aimlapi.com](https://aimlapi.com) → API Keys |
| `BRIGHTDATA_BROWSER_AUTH` | Bright Data dashboard → Scraping Browser zone → Access Parameters → `username:password` |
| `XAI_API_KEY` | [console.x.ai](https://console.x.ai) → API Keys — enables KOL Twitter/X ingestion via Grok |

### 4. Validate connections

```bash
python test_connections.py
```

All four required checks (AI/ML API, Bright Data, Reddit RSS, bioRxiv/medRxiv) should show `✓ PASS` before proceeding.

### 5. Run the dashboard

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Using the Dashboard

### Thesis Control Center (sidebar)

| Control | Description |
|---------|-------------|
| **Biological Pathway** | The pathway to track. Try `IL-6 signaling`, `GLP-1 receptor`, `JAK-STAT`, `mTOR`, `PD-1/PD-L1`, `mRNA delivery`. |
| **Days of preprint history** | How far back to pull bioRxiv/medRxiv records. 3–7 days is a good default; use 14 for broad coverage. |
| **Include ChemRxiv** | Adds preclinical pharmacology papers. Slower but adds signal depth. |
| **X / Twitter KOL Handles** | Enter any number of public X handles (one per line or comma-separated, `@` optional). Grok searches their recent posts for pathway signals. Requires `XAI_API_KEY` in `.env`. Pre-populated from `kol_handles.json`. |
| **Report model** | `gpt-4o` for speed; `o1` for deeper scientific reasoning. |
| **Run Analysis** | Triggers the full pipeline. First run takes 2–4 minutes; subsequent runs load from a 1-hour cache instantly. |
| **Clear Cache** | Forces a fresh data pull and re-analysis. |

### Reading the Arbitrage Matrix

- **Central node** — the biological pathway you searched
- **Child nodes** — novel therapeutic indications where the pathway was detected
- **Crimson animated edges** — high-confidence signals (≥50% confidence score)
- **Gray edges** — weak or speculative signals (<50%)
- **Intelligence Report** — Bear / Bull / Neutral verdict with immunological soundness evaluation, ranked signal quality, risk factors, and a company/trial watch list

---

## Data Sources

| Source | Access Method | Cost | Notes |
|--------|--------------|------|-------|
| bioRxiv | REST API (`api.biorxiv.org`) | Free, no auth | Zero-authentication, paginated JSON |
| medRxiv | REST API (`api.biorxiv.org`) | Free, no auth | Same API as bioRxiv, `server=medrxiv` |
| Reddit | Atom RSS feed | Free, no auth | `reddit.com/r/{sub}/new.rss` — no OAuth required |
| X / Twitter | Grok `x_search` tool (xAI API) | ~$0.005/run | Requires `XAI_API_KEY`; enter handles in sidebar; max 20 |
| ChemRxiv | REST API (`chemrxiv.org`) | Free, no auth | Pharmacology/biochemistry filter; enable via sidebar checkbox |
| Bright Data | Scraping Browser (WebSocket) | $250 budget | Used for web targets requiring anti-bot evasion |

> **Note on Reddit:** Reddit's JSON API and their Scraping Browser are both blocked (API requires OAuth; Bright Data respects Reddit's robots.txt). The RSS feed is the reliable zero-friction path and is explicitly permitted.

> **Note on X/Twitter:** The free Twitter API is write-only. Bright Data's Scraping Browser cannot access X due to robots.txt compliance. PathwayPulse uses the Grok xAI Responses API (`x_search` tool) as the only reliable free-access path to public X posts.

---

## AI Pipeline

### Synthesizer — DeepSeek-V3 via AI/ML API

- Processes records in async batches of up to 10 concurrent requests
- Returns structured `CrossPollinationEvent` objects via `json_object` mode
- Failures are logged to `errors.log` and skipped — the pipeline never halts
- Cost: ~$0.001 per record at AI/ML API pricing

### Executioner — GPT-4o via OpenAI

- Called once per analysis run, after all events are collected
- Evaluates immunological soundness and writes the Bear/Bull/Neutral report
- Cost: ~$0.01–0.05 per report depending on event count

### Budget protection

- `@st.cache_data(ttl=3600)` on all ingestion functions — graph interactions never re-trigger APIs
- `return_exceptions=True` in `asyncio.gather` — one bad record never kills the batch
- bioRxiv/medRxiv capped at 300 records per server per run during testing

---

## Running Tests

```bash
# Validate all API connections
python test_connections.py

# Test the AI pipeline with built-in sample abstracts
python ai_orchestrator.py

# Test ingestion agents independently
python swarm_ingestion.py
```

---

## Future Directions

See [Future Directions](#future-directions-1) below for the full list.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `streamlit` | Dashboard framework |
| `streamlit-flow-component` | Interactive node graph |
| `openai` | OpenAI SDK (used for both OpenAI and AI/ML API via `base_url`) |
| `pydantic` | Structured output schema validation |
| `requests` | HTTP calls to preprint APIs and Reddit RSS |
| `tenacity` | Exponential backoff retry logic |
| `playwright` | Headless browser automation (Bright Data Scraping Browser) |
| `python-dotenv` | `.env` file loading |
| `openai` (pointed at `api.x.ai`) | Grok xAI Responses API for x_search KOL ingestion |

---

## Future Directions

### High-Priority Improvements

**1. Expand data sources**
- **SEC EDGAR filings** — Parse 8-K, 10-K, and S-1 filings for language about pipeline pivots and new indication trials. Companies often bury cross-indication language in footnotes months before press releases.
- **ClinicalTrials.gov API** — Free REST API (`clinicaltrials.gov/api/v2`) that exposes every registered trial. Cross-reference pathway keywords with new indication categories for definitive ground-truth signals.
- **PubMed/NCBI Entrez API** — Peer-reviewed publications lag preprints by 6–18 months but carry more weight. Layering PubMed on top of bioRxiv creates a signal maturity timeline.
- **Biotech conference abstracts** — ASCO, ASH, EASD, and ACR publish abstract books before presentations. These are the earliest public disclosures of trial data.

**2. Temporal signal tracking**
Currently PathwayPulse is a point-in-time snapshot. A time-series view that tracks how a signal's confidence score changes week-over-week would show whether a thesis is strengthening or fading. Store results in a local SQLite database and add a "Signal Momentum" chart to the dashboard.

**3. Entity extraction**
The current `source_evidence` field is a raw text snippet. Adding named entity recognition (NER) — specifically for drug names, company names, trial IDs, and gene targets — would let you automatically populate the watch list with verified entities rather than relying on GPT-4o to infer them.

**4. Automatic ticker mapping**
Map detected novel indications to publicly traded companies with active programs in that area (using a curated `indication_to_tickers.json` lookup, or a secondary GPT call). This would turn a biological signal directly into a tradeable equity watch list.

**5. Bright Data for SEC / conference sites**
The Scraping Browser budget is currently unused (Reddit was blocked). High-value targets that genuinely need anti-bot evasion: SEC EDGAR full-text search, conference abstract portals (ASCO, ASH), and biotech IR pages. These are the right use cases for the Scraping Browser.

### Medium-Priority Improvements

**6. Confidence score calibration**
DeepSeek-V3 tends to cluster confidence scores around 0.85–0.95. A calibration layer (isotonic regression or Platt scaling against a small labelled validation set) would make scores more meaningful and spread out.

**7. Pathway ontology**
Right now pathway input is free text (`IL-6 signaling`, `JAK-STAT`). Integrating a biomedical ontology like Reactome or Gene Ontology would let users browse a structured hierarchy of pathways and ensure consistent terminology across runs.

**8. Multi-pathway comparison**
Allow the user to run analyses on several pathways simultaneously and display them as overlapping subgraphs — useful for comparing IL-6 vs. IL-17 vs. TNF-alpha repurposing trajectories side-by-side.

**9. Email / Slack alerts**
Schedule the pipeline to run nightly (via `cron` or GitHub Actions) and push a summary to Slack or email when a new high-confidence signal appears that wasn't in the previous run.

**10. RAG memory layer**
Store all past `CrossPollinationEvent` objects in a vector database (e.g., ChromaDB). When new events are detected, retrieve the most similar past signals to give the Executioner historical context — "this same pathway showed up in lupus 6 months ago with 0.4 confidence; it's now at 0.9."

### Stretch Goals

- **Interactive node graph editing** — let users manually add/remove nodes, annotate edges with investment thesis notes, and export the graph as a PDF
- **Multi-language preprint support** — bioRxiv indexes preprints in all languages; add translation via DeepSeek before synthesis
- **Fine-tuned Synthesizer** — replace the zero-shot DeepSeek prompt with a model fine-tuned on a curated dataset of confirmed cross-indication repurposing events (e.g., all approved drug repurposings from the past decade)

---

## License

MIT

---

## Acknowledgments

Built with [Bright Data](https://brightdata.com), [AI/ML API](https://aimlapi.com), [OpenAI](https://openai.com), [bioRxiv](https://biorxiv.org), [medRxiv](https://medrxiv.org), and [Streamlit](https://streamlit.io).
