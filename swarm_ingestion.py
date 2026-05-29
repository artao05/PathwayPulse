"""
PathwayPulse — Ingestion Swarm
Four agents feed raw text into the AI orchestrator:
  1. extract_reddit_alpha   — biotech community signal via public Atom RSS feed
  2. fetch_preprints        — bioRxiv + medRxiv clinical preprints (shared paginator)
  3. fetch_x_kol_grok       — KOL tweets via Grok xAI x_search tool (optional)
  4. fetch_chemrxiv         — preclinical pharmacology (stretch goal)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, timedelta
from typing import Any, List, Optional

import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_BIORXIV_BASE = "https://api.biorxiv.org/details/{server}/{start}/{end}/{cursor}"
_CHEMRXIV_BASE = "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items"
_MAX_RECORDS_PER_SERVER = 300

_PREPRINT_URL_BASES = {
    "biorxiv": "https://www.biorxiv.org",
    "medrxiv": "https://www.medrxiv.org",
}


def _preprint_url(server: str, doi: str) -> str:
    """Build canonical preprint URL from server name and DOI."""
    base = _PREPRINT_URL_BASES.get(server, "https://www.biorxiv.org")
    return f"{base}/content/{doi}v1" if doi else ""


def _source_label(record: dict) -> str:
    """Return a human-readable source label for display in the UI."""
    src = record.get("source", "")
    if src == "reddit":
        return f"r/{record.get('subreddit', 'reddit')}"
    if src == "twitter":
        handle = record.get("handle", "")
        return f"@{handle}" if handle else "X/Twitter"
    if src in ("biorxiv", "medrxiv"):
        return src.replace("biorxiv", "bioRxiv").replace("medrxiv", "medRxiv")
    if src == "chemrxiv":
        return "ChemRxiv"
    return src


# ── 1. Reddit RSS Feed (no auth, no PRAW, no Bright Data) ────────────────────
# Reddit's Atom RSS feeds are publicly accessible for all public subreddits
# without OAuth or API registration. Reddit's JSON API is blocked for
# non-OAuth clients; the Scraping Browser cannot access Reddit via robots.txt.
# RSS is the reliable zero-friction path.

import re as _re
import xml.etree.ElementTree as _ET

_CLINICAL_KEYWORDS = {
    "trial", "phase", "indication", "pathway", "inhibitor", "antibody",
    "autoimmune", "oncology", "immunology", "fda", "anda", "nda", "bla",
    "efficacy", "safety", "mechanism", "target", "receptor", "signaling",
    "repurposing", "off-label", "preclinical", "clinical",
}
_TICKER_RE = _re.compile(r"\$[A-Z]{2,5}")
_REDDIT_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PathwayPulse/1.0)"}
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_HTML_TAG_RE = _re.compile(r"<[^>]+>")


@retry(wait=wait_exponential(multiplier=1, min=5, max=30), stop=stop_after_attempt(3))
def _reddit_rss_get(url: str) -> bytes:
    resp = requests.get(url, headers=_REDDIT_HEADERS, timeout=15)
    if resp.status_code == 429:
        raise RuntimeError("Reddit rate limit — will retry with backoff")
    resp.raise_for_status()
    return resp.content


def extract_reddit_alpha(subreddit: str = "biotech", limit: int = 50) -> list[dict]:
    """
    Fetch recent posts from r/{subreddit} via the public Atom RSS feed.
    No API keys, PRAW, or Bright Data required.
    RSS feeds are allowed by Reddit for public subreddits.
    Returns [] gracefully on any failure.
    """
    results: list[dict] = []
    try:
        url = f"https://www.reddit.com/r/{subreddit}/new.rss?limit={min(limit, 100)}"
        raw = _reddit_rss_get(url)
        root = _ET.fromstring(raw)
        entries = root.findall("atom:entry", _ATOM_NS)

        for entry in entries:
            title = entry.findtext("atom:title", default="", namespaces=_ATOM_NS).strip()
            link_el = entry.find("atom:link", _ATOM_NS)
            post_url = link_el.get("href", "") if link_el is not None else ""

            # Content is HTML-escaped; strip tags for clean text
            raw_content = entry.findtext("atom:content", default="", namespaces=_ATOM_NS)
            body = _HTML_TAG_RE.sub(" ", raw_content).strip()[:2000]

            combined = (title + " " + body).lower()
            has_ticker = bool(_TICKER_RE.search(title + body))
            has_link = bool(post_url and "/r/" not in post_url.rstrip("/").rsplit("/", 1)[-1])
            has_keyword = any(kw in combined for kw in _CLINICAL_KEYWORDS)

            if not (has_ticker or has_link or has_keyword):
                continue

            results.append({
                "source": "reddit",
                "subreddit": subreddit,
                "source_label": f"r/{subreddit}",
                "title": title,
                "body": body,
                "url": post_url,
                "flair": None,   # not available in RSS feed
                "score": 0,      # not available in RSS feed
            })

        log.info("Reddit RSS: %d filtered posts from r/%s", len(results), subreddit)
        return results

    except Exception as e:
        log.warning("Reddit RSS failed for r/%s (%s) — returning []", subreddit, e)
        return []


async def extract_reddit_playwright(subreddit: str = "biotech", limit: int = 50) -> list[dict]:
    """Async wrapper — name kept for ingest_all compatibility."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, extract_reddit_alpha, subreddit, limit)


# ── 2. bioRxiv / medRxiv (shared paginator) ───────────────────────────────────

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(4))
def _fetch_page(url: str) -> dict:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_preprints(server: str = "biorxiv", days_back: int = 3) -> list[dict]:
    """
    Fetch preprints from bioRxiv or medRxiv via the shared api.biorxiv.org REST API.
    server: 'biorxiv' or 'medrxiv'
    Returns list of dicts with keys: source, doi, title, abstract, category, date
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    cursor = 0
    records: list[dict] = []

    while len(records) < _MAX_RECORDS_PER_SERVER:
        url = _BIORXIV_BASE.format(
            server=server,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            cursor=cursor,
        )
        try:
            data = _fetch_page(url)
        except Exception as e:
            log.warning("%s pagination stopped at cursor=%d (%s)", server, cursor, e)
            break

        collection = data.get("collection", [])
        if not collection:
            break

        for item in collection:
            doi = item.get("doi", "")
            records.append({
                "source": server,
                "doi": doi,
                "url": _preprint_url(server, doi),
                "source_label": server.replace("biorxiv", "bioRxiv").replace("medrxiv", "medRxiv"),
                "title": item.get("title", ""),
                "abstract": item.get("abstract", ""),
                "category": item.get("category", ""),
                "date": item.get("date", ""),
            })

        if len(collection) < 100:
            break
        cursor += 100

    log.info("%s: fetched %d records (days_back=%d)", server, len(records), days_back)
    return records[:_MAX_RECORDS_PER_SERVER]


async def fetch_all_preprints(days_back: int = 3) -> list[dict]:
    """Fetch bioRxiv and medRxiv in parallel."""
    loop = asyncio.get_event_loop()
    biorxiv_task = loop.run_in_executor(None, fetch_preprints, "biorxiv", days_back)
    medrxiv_task = loop.run_in_executor(None, fetch_preprints, "medrxiv", days_back)
    results = await asyncio.gather(biorxiv_task, medrxiv_task, return_exceptions=True)
    combined = []
    for server, result in zip(("biorxiv", "medrxiv"), results):
        if isinstance(result, Exception):
            log.warning("%s fetch raised exception: %s", server, result)
        else:
            combined.extend(result)
    log.info("Preprints total: %d records", len(combined))
    return combined


# ── 3. X / Twitter KOL via Grok x_search ─────────────────────────────────────
# Uses xAI's official Responses API with the x_search tool.
# No Twitter developer account needed — Grok fetches public X data on our behalf.
# One API call per analysis run covers all handles in a single request.
# Cost: ~$0.005 per run at $5/1,000 x_search calls with 1-hour caching.

_XAI_BASE_URL = "https://api.x.ai/v1"
_XAI_MODEL = "grok-3-latest"
_MAX_HANDLES = 20  # xAI API limit for allowed_x_handles


def fetch_x_kol_grok(
    handles: Optional[List[str]] = None,
    pathway: str = "",
    days_back: int = 3,
) -> list[dict]:
    """
    Fetch recent X/Twitter posts from a curated list of KOL handles using
    the Grok xAI Responses API with the x_search tool.

    Returns [] if XAI_API_KEY is not set or handles list is empty.
    Truncates to 20 handles (xAI API limit) with a logged warning.
    Never raises — pipeline continues unaffected on any failure.
    """
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        log.info("XAI_API_KEY not set — Grok KOL agent returning [] (set key to enable X/Twitter ingestion)")
        return []

    handles = [h.lstrip("@").strip() for h in (handles or []) if h.strip()]
    if not handles:
        log.info("No KOL handles provided — Grok agent returning []")
        return []

    if len(handles) > _MAX_HANDLES:
        log.warning(
            "KOL handle list has %d entries — truncating to first %d (xAI API limit)",
            len(handles), _MAX_HANDLES,
        )
        handles = handles[:_MAX_HANDLES]

    from_date = (date.today() - timedelta(days=days_back)).isoformat()
    pathway_clause = f" related to {pathway}" if pathway else ""

    prompt = (
        f"Search recent public X posts from these accounts{pathway_clause}. "
        f"Return a JSON array (no markdown, no explanation) where each element has: "
        f'"handle" (string), "text" (full post text), "url" (post URL or empty string). '
        f"Include only posts that are substantively about biology, medicine, drug development, "
        f"or clinical research. Return an empty array [] if nothing relevant is found."
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=_XAI_BASE_URL)

        response = client.responses.create(
            model=_XAI_MODEL,
            input=[{"role": "user", "content": prompt}],
            tools=[{
                "type": "x_search",
                "allowed_x_handles": handles,
                "from_date": from_date,
            }],
        )

        # Extract text content from the response
        raw = ""
        for item in response.output:
            if hasattr(item, "content"):
                for block in item.content:
                    if hasattr(block, "text"):
                        raw += block.text

        # Strip accidental markdown code fences
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        if not raw or raw == "[]":
            log.info("Grok x_search: no relevant posts found for handles %s", handles)
            return []

        import json as _json
        posts = _json.loads(raw)
        if not isinstance(posts, list):
            log.warning("Grok x_search: unexpected response shape — expected list, got %s", type(posts))
            return []

        results = []
        for post in posts:
            if not isinstance(post, dict):
                continue
            text = str(post.get("text", "")).strip()
            if not text:
                continue
            handle = str(post.get("handle", ""))
            post_url = str(post.get("url", ""))
            # Fall back to profile URL if Grok returned no post-level link
            display_url = post_url or (f"https://x.com/{handle}" if handle else "")
            results.append({
                "source": "twitter",
                "handle": handle,
                "source_label": f"@{handle}" if handle else "X/Twitter",
                "title": text[:80],
                "body": text,
                "url": display_url,
            })

        log.info("Grok x_search: %d relevant posts from %d handles", len(results), len(handles))
        return results

    except Exception as e:
        log.warning("Grok x_search agent failed (%s: %s) — returning []", type(e).__name__, e)
        return []


# ── 4. ChemRxiv (stretch goal — preclinical pharmacology) ────────────────────

def fetch_chemrxiv(days_back: int = 7) -> list[dict]:
    """
    Fetch recent pharmacology/biochemistry preprints from ChemRxiv.
    Uses a different REST API from bioRxiv. Zero-auth, free.
    Returns [] on any failure so the pipeline is unaffected.
    """
    target_categories = {
        "pharmacology", "biochemistry", "medicinal chemistry",
        "drug discovery", "chemical biology", "toxicology",
    }
    cutoff = date.today() - timedelta(days=days_back)
    skip = 0
    limit = 25
    records: list[dict] = []

    while len(records) < 100:
        try:
            params: dict[str, Any] = {
                "sort": "published_date",
                "limit": limit,
                "skip": skip,
            }
            resp = requests.get(_CHEMRXIV_BASE, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning("ChemRxiv fetch error at skip=%d: %s", skip, e)
            break

        items = data.get("itemHits", [])
        if not items:
            break

        for hit in items:
            item = hit.get("item", {})
            pub_date_str = item.get("publishedDate", "")
            try:
                pub_date = date.fromisoformat(pub_date_str[:10])
            except Exception:
                pub_date = date.min

            if pub_date < cutoff:
                # Results are sorted descending; once we pass cutoff, stop
                return records

            categories = {s.get("name", "").lower() for s in item.get("subjects", [])}
            if not categories.intersection(target_categories):
                continue

            doi = item.get("doi", "")
            records.append({
                "source": "chemrxiv",
                "doi": doi,
                "url": f"https://doi.org/{doi}" if doi else "",
                "source_label": "ChemRxiv",
                "title": item.get("title", ""),
                "abstract": item.get("abstract", ""),
                "category": ", ".join(categories),
                "date": pub_date_str[:10],
            })

        skip += limit

    log.info("ChemRxiv: fetched %d records (days_back=%d)", len(records), days_back)
    return records


# ── Convenience: run all agents ───────────────────────────────────────────────

async def ingest_all(
    pathway_hint: str = "",
    reddit_subreddits: Optional[List[str]] = None,
    twitter_handles: Optional[List[str]] = None,
    days_back: int = 3,
    include_chemrxiv: bool = False,
) -> list[dict]:
    """
    Run all ingestion agents and return a unified list of records.
    Each record has at minimum: source, title/text, abstract/body.
    """
    subreddits = reddit_subreddits or ["biotech", "investing", "stocks"]

    loop = asyncio.get_event_loop()

    # Reddit tasks are async (Playwright) — run sequentially to avoid competing
    # for the same Bright Data browser session; parallel sessions cost extra bandwidth
    reddit_tasks = [extract_reddit_playwright(sub, 50) for sub in subreddits]
    preprint_task = fetch_all_preprints(days_back)
    twitter_task = loop.run_in_executor(
        None, fetch_x_kol_grok, twitter_handles or [], pathway_hint, days_back
    )

    reddit_results, preprint_results, twitter_results = await asyncio.gather(
        asyncio.gather(*reddit_tasks, return_exceptions=True),
        preprint_task,
        twitter_task,
        return_exceptions=False,
    )

    all_records: list[dict] = []
    for result in reddit_results:
        if isinstance(result, list):
            all_records.extend(result)

    all_records.extend(preprint_results)
    all_records.extend(twitter_results)

    if include_chemrxiv:
        chemrxiv_results = await loop.run_in_executor(None, fetch_chemrxiv, days_back)
        all_records.extend(chemrxiv_results)

    log.info("Ingestion complete: %d total records", len(all_records))
    return all_records


if __name__ == "__main__":
    async def _demo():
        posts = await extract_reddit_playwright("biotech", limit=10)
        print(f"\nReddit posts from r/biotech: {len(posts)}")
        for p in posts[:5]:
            print(f"  [{p['score']:>5}] {p['title'][:80]}")

        # Grok x_search demo (requires XAI_API_KEY in .env)
        kol_posts = fetch_x_kol_grok(["EricTopol", "BioPharmaDive"], "IL-6 signaling", days_back=3)
        print(f"\nGrok KOL posts: {len(kol_posts)}")
        for p in kol_posts[:3]:
            print(f"  @{p['handle']}: {p['body'][:80]}")

        # Full ingest (preprints only if no Bright Data key)
        records = await ingest_all(days_back=1, include_chemrxiv=False)
        print(f"\nTotal records ingested: {len(records)}")
        for r in records[:3]:
            print(f"  [{r['source']}] {r.get('title', r.get('text', ''))[:80]}")

    asyncio.run(_demo())
