# Deploy PathwayPulse to Streamlit Community Cloud

Use this guide to publish the app for hackathon judges at **https://share.streamlit.io**.

## What works on Streamlit Cloud

| Feature | Cloud support |
|---------|---------------|
| bioRxiv / medRxiv preprints | Yes |
| Reddit RSS | Yes |
| Catalyst Calendar (CT.gov API v2) | Yes |
| DeepSeek-V3 synthesis + GPT-4o report | Yes (requires secrets) |
| Grok X/Twitter KOL ingestion | Yes (optional `XAI_API_KEY`) |
| BrightData ACR / ASCO abstracts | Yes if `BRIGHTDATA_BROWSER_AUTH` is set — Playwright uses BrightData's remote browser (no local Chromium) |
| ClinicalTrials.gov text scrape | Blocked by BrightData `.gov` policy; API v2 fallback still works |

**Expected run time:** ~2–4 minutes on first analysis (no ACR), ~4–5 minutes with ACR enabled.

---

## Step 1 — Push the repo to GitHub

The repo must be public (or connected to a Streamlit Cloud account with access):

```bash
git push origin main
```

Repo: **https://github.com/artao05/PathwayPulse**

---

## Step 2 — Create the Streamlit Cloud app

1. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub.
2. Click **New app**.
3. Set:
   - **Repository:** `artao05/PathwayPulse`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **Advanced settings** → set **Python version** to `3.11` if offered.
5. Click **Deploy**.

The first build takes 2–3 minutes while dependencies install.

---

## Step 3 — Add secrets

In the deployed app: **⋮ (menu) → Settings → Secrets**, paste:

```toml
OPENAI_API_KEY = "sk-your-openai-key"
AIMLAPI_KEY = "your-aimlapi-key"
XAI_API_KEY = "xai-your-key"

# Optional — full BrightData scraping (ACR abstracts, etc.)
BRIGHTDATA_BROWSER_AUTH = "brd-customer-XXXX-zone-scraping_browser:XXXX"
```

Click **Save**. Streamlit will reboot the app automatically.

See [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) for the full template.

**Minimum required for a working demo:** `OPENAI_API_KEY` and `AIMLAPI_KEY`.

---

## Step 4 — Smoke test

1. Open the public app URL (e.g. `https://pathwaypulse.streamlit.app`).
2. Leave the default pathway **IL-6 signaling**.
3. Ensure **Show Catalyst Calendar** is checked.
4. Leave conference abstracts unchecked if `BRIGHTDATA_BROWSER_AUTH` is not set (faster demo).
5. Click **Run Analysis** and wait ~2–4 minutes.
6. Confirm you see:
   - Metrics row (Records Ingested, Signals Detected, …)
   - Arbitrage Matrix node graph
   - Intelligence Report (Bear / Bull / Neutral)
   - Catalyst Calendar expander

---

## Step 5 — Share with judges

Send the public Streamlit URL plus this quick-start:

> **PathwayPulse demo**
> 1. Open the app URL
> 2. Pathway is pre-filled (`IL-6 signaling`) — click **Run Analysis**
> 3. First run takes ~2–4 minutes; results include a node graph, AI report, and trial readout calendar
> 4. Try other pathways: `JAK-STAT pathway`, `GLP-1 receptor`, `PD-1 / PD-L1`

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| App crashes on startup | Check **Manage app → Logs**; verify `requirements.txt` installed cleanly |
| "Run Analysis" does nothing / errors | Confirm `OPENAI_API_KEY` and `AIMLAPI_KEY` are set in Secrets |
| No Twitter/KOL data | Expected if `XAI_API_KEY` is missing — optional feature |
| Conference abstracts disabled | Set `BRIGHTDATA_BROWSER_AUTH` in Secrets, then select ACR in sidebar |
| Slow first run | Normal — ingestion + ~350 LLM calls; cached runs are faster within 1 hour |
| Secrets not picked up | Secrets load via `secrets_loader.py`; reboot app after saving Secrets |

---

## Local vs Cloud

| | Local (`streamlit run app.py`) | Streamlit Cloud |
|--|-------------------------------|-----------------|
| API keys | `.env` file | App Settings → Secrets |
| BrightData | Same secret key | Same — remote CDP, no local Chromium |
| Cache | 1-hour TTL per machine | 1-hour TTL per app instance |
