"""
PathwayPulse — Ingestion Swarm
Agents feed raw text into the AI orchestrator:
  1. extract_reddit_alpha          — biotech community signal via public Atom RSS feed
  2. fetch_preprints               — bioRxiv + medRxiv clinical preprints (shared paginator)
  3. fetch_pubmed_literature       — peer-reviewed abstracts via NCBI E-utilities
  4. annotate_openalex_citations   — citation counts / journal locations for preprints
  5. fetch_x_kol_grok              — KOL tweets via Grok xAI x_search tool (optional)
  6. fetch_clinicaltrials_api       — ClinicalTrials.gov via free API v2 (no auth)
  7. fetch_trial_catalysts         — Catalyst Calendar: API v2 discovery + enrichment
  8. fetch_chemrxiv                — preclinical pharmacology (stretch goal)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, timedelta
from typing import Any, List, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from secrets_loader import load_secrets

load_secrets()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_BIORXIV_BASE = "https://api.biorxiv.org/details/{server}/{start}/{end}/{cursor}"
_CHEMRXIV_BASE = "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items"
_CT_API_BASE = "https://clinicaltrials.gov/api/v2/studies"
_NCBI_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_OPENALEX_BASE = "https://api.openalex.org"
_CT_FIELDS = (
    "NCTId,BriefTitle,OverallStatus,StartDateStruct,PrimaryCompletionDateStruct,"
    "CompletionDateStruct,ResultsFirstPostDateStruct,Phase,LeadSponsorName,"
    "InterventionName,Condition"
)
_MAX_RECORDS_PER_SERVER = 300
_MAX_PUBMED_RECORDS = 50
_OPENALEX_CHUNK_SIZE = 50

_PREPRINT_URL_BASES = {
    "biorxiv": "https://www.biorxiv.org",
    "medrxiv": "https://www.medrxiv.org",
}
_OPENALEX_PREPRINT_SOURCES = {"biorxiv", "medrxiv", "chemrxiv"}
_PREPRINT_SOURCE_NAME_FRAGMENTS = ("biorxiv", "medrxiv", "chemrxiv")
_ENV_PLACEHOLDER_TOKENS = (
    "...",
    "replace-with",
    "sk-replace-with",
    "brd-customer-xxxx",
    "you@example.com",
)


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
    if src == "pubmed":
        return "PubMed"
    if src == "chemrxiv":
        return "ChemRxiv"
    return src


def _configured_env(key: str) -> str:
    value = os.getenv(key, "").strip()
    normalized = value.lower()
    if not value or any(token in normalized for token in _ENV_PLACEHOLDER_TOKENS):
        return ""
    return value


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


# ── 2B. PubMed peer-reviewed literature (NCBI E-utilities) ───────────────────

def _ncbi_env_params() -> dict[str, str]:
    """Return optional NCBI request parameters without exposing secrets."""
    params = {"tool": os.getenv("NCBI_TOOL", "PathwayPulse")}
    email = _configured_env("USER_EMAIL")
    api_key = _configured_env("NCBI_API_KEY")
    if email:
        params["email"] = email
    if api_key:
        params["api_key"] = api_key
    return params


@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def _ncbi_get(endpoint: str, params: dict[str, Any], *, raw: bool = False) -> Any:
    resp = requests.get(
        f"{_NCBI_EUTILS_BASE}/{endpoint}",
        params={**_ncbi_env_params(), **params},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.text if raw else resp.json()


def _xml_text(element: Optional[_ET.Element]) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _pubmed_date(article: _ET.Element) -> str:
    pub_date = article.find(".//Journal/JournalIssue/PubDate")
    if pub_date is None:
        return ""
    year = pub_date.findtext("Year") or ""
    month = pub_date.findtext("Month") or ""
    day = pub_date.findtext("Day") or ""
    medline = pub_date.findtext("MedlineDate") or ""
    return " ".join(p for p in (year, month, day) if p).strip() or medline


def _pubmed_abstract(article: _ET.Element) -> str:
    parts: list[str] = []
    for abstract_text in article.findall(".//Abstract/AbstractText"):
        label = abstract_text.get("Label", "").strip()
        text = _xml_text(abstract_text)
        if not text:
            continue
        parts.append(f"{label}: {text}" if label else text)
    return "\n".join(parts)


def fetch_pubmed_literature(
    pathway: str,
    days_back: int = 30,
    max_results: int = _MAX_PUBMED_RECORDS,
) -> list[dict]:
    """
    Fetch recent peer-reviewed literature from PubMed via NCBI E-utilities.

    Returns records shaped for the Synthesizer:
    {source, pmid, doi, url, source_label, title, abstract, journal, date}
    Returns [] on any failure so the pipeline continues unaffected.
    """
    pathway = pathway.strip()
    if not pathway:
        return []

    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    date_filter = f"{start_date:%Y/%m/%d}:{end_date:%Y/%m/%d}[dp]"
    query = f"({pathway}) AND ({date_filter})"

    try:
        search_data = _ncbi_get(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": query,
                "retmax": min(max_results, _MAX_PUBMED_RECORDS),
                "sort": "pub_date",
                "retmode": "json",
            },
        )
        pmids = search_data.get("esearchresult", {}).get("idlist", [])
        if not pmids:
            log.info("PubMed: no records for '%s' (days_back=%d)", pathway, days_back)
            return []

        xml_data = _ncbi_get(
            "efetch.fcgi",
            {
                "db": "pubmed",
                "id": ",".join(pmids),
                "rettype": "abstract",
                "retmode": "xml",
            },
            raw=True,
        )
        root = _ET.fromstring(xml_data)
    except Exception as e:
        log.warning("PubMed fetch failed (%s: %s) — returning []", type(e).__name__, e)
        return []

    records: list[dict] = []
    for pubmed_article in root.iter("PubmedArticle"):
        medline = pubmed_article.find(".//MedlineCitation")
        article = pubmed_article.find(".//Article")
        if article is None:
            continue

        pmid = _xml_text(pubmed_article.find(".//PMID"))
        title = _xml_text(article.find("ArticleTitle"))
        abstract = _pubmed_abstract(article)
        if not (pmid and title and abstract):
            continue

        doi = ""
        for article_id in pubmed_article.findall(".//ArticleIdList/ArticleId"):
            if article_id.get("IdType") == "doi" and article_id.text:
                doi = article_id.text.strip()
                break
        if not doi:
            for eid in article.findall("ELocationID"):
                if eid.get("EIdType") == "doi" and eid.text:
                    doi = eid.text.strip()
                    break

        authors: list[str] = []
        for author in article.findall(".//AuthorList/Author")[:6]:
            last = author.findtext("LastName") or ""
            initials = author.findtext("Initials") or ""
            collective = author.findtext("CollectiveName") or ""
            name = f"{last} {initials}".strip() if last else collective.strip()
            if name:
                authors.append(name)

        records.append({
            "source": "pubmed",
            "pmid": pmid,
            "doi": doi,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "source_label": "PubMed",
            "title": title,
            "abstract": abstract[:3000],
            "journal": _xml_text(article.find(".//Journal/Title")),
            "date": _pubmed_date(medline if medline is not None else article),
            "authors": authors,
        })

    log.info("PubMed: fetched %d abstracts for '%s'", len(records), pathway)
    return records


async def fetch_pubmed_literature_async(
    pathway: str,
    days_back: int = 30,
    max_results: int = _MAX_PUBMED_RECORDS,
) -> list[dict]:
    """Async wrapper for PubMed ingestion."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, fetch_pubmed_literature, pathway, days_back, max_results
    )


# ── 2C. OpenAlex citation enrichment for preprints ───────────────────────────

def _openalex_params(params: dict[str, Any]) -> dict[str, Any]:
    merged = dict(params)
    api_key = _configured_env("OPENALEX_API_KEY")
    email = _configured_env("USER_EMAIL")
    if api_key:
        merged["api_key"] = api_key
    elif email:
        merged["mailto"] = email
    return merged


@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def _openalex_get(path: str, params: dict[str, Any]) -> dict:
    resp = requests.get(
        f"{_OPENALEX_BASE}/{path.lstrip('/')}",
        params=_openalex_params(params),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _normalize_doi(doi: str) -> str:
    doi = (doi or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi.strip()


def _preprint_source_name(source_name: str) -> bool:
    normalized = source_name.lower()
    return any(fragment in normalized for fragment in _PREPRINT_SOURCE_NAME_FRAGMENTS)


def _journal_location(work: dict) -> dict:
    locations: list[dict] = []
    for key in ("primary_location", "best_oa_location"):
        value = work.get(key)
        if isinstance(value, dict):
            locations.append(value)
    locations.extend([loc for loc in work.get("locations", []) if isinstance(loc, dict)])

    for location in locations:
        source = location.get("source") or {}
        source_name = source.get("display_name") or ""
        source_type = source.get("type") or ""
        if source_type == "journal" and not _preprint_source_name(source_name):
            return {
                "published_version_source": source_name,
                "published_version_url": location.get("landing_page_url") or "",
                "published_version_is_oa": bool(location.get("is_oa")),
            }
    return {}


def _openalex_metadata(work: dict) -> dict:
    metadata = {
        "openalex_id": work.get("id", ""),
        "openalex_url": work.get("id", ""),
        "citation_count": int(work.get("cited_by_count") or 0),
        "openalex_publication_year": work.get("publication_year"),
        "openalex_publication_date": work.get("publication_date") or "",
    }
    metadata.update(_journal_location(work))
    metadata["published_in_journal"] = bool(metadata.get("published_version_source"))
    return metadata


def annotate_openalex_citations(records: list[dict]) -> list[dict]:
    """
    Add OpenAlex citation metadata to DOI-bearing preprint records.

    The function mutates and returns the input list. API failures are logged and
    leave records unchanged.
    """
    doi_records = [
        rec for rec in records
        if rec.get("source") in _OPENALEX_PREPRINT_SOURCES and _normalize_doi(rec.get("doi", ""))
    ]
    if not doi_records:
        return records

    work_by_doi: dict[str, dict] = {}
    try:
        for i in range(0, len(doi_records), _OPENALEX_CHUNK_SIZE):
            chunk = doi_records[i : i + _OPENALEX_CHUNK_SIZE]
            doi_filter = "|".join(_normalize_doi(rec.get("doi", "")) for rec in chunk)
            data = _openalex_get(
                "works",
                {
                    "filter": f"doi:{doi_filter}",
                    "per_page": len(chunk),
                    "select": (
                        "id,doi,display_name,cited_by_count,publication_year,"
                        "publication_date,primary_location,best_oa_location,locations,type"
                    ),
                },
            )
            for work in data.get("results", []):
                doi = _normalize_doi(work.get("doi", ""))
                if doi:
                    work_by_doi[doi] = work
    except Exception as e:
        log.warning("OpenAlex citation enrichment failed (%s: %s) — leaving records unchanged", type(e).__name__, e)
        return records

    enriched_count = 0
    for rec in doi_records:
        work = work_by_doi.get(_normalize_doi(rec.get("doi", "")))
        if not work:
            continue
        rec.update(_openalex_metadata(work))
        enriched_count += 1

    log.info(
        "OpenAlex: enriched %d / %d DOI-bearing preprints",
        enriched_count,
        len(doi_records),
    )
    return records


async def annotate_openalex_citations_async(records: list[dict]) -> list[dict]:
    """Async wrapper for OpenAlex citation enrichment."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, annotate_openalex_citations, records)


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


# ── 4. ClinicalTrials.gov via API v2 (no BrightData required) ────────────────
# Direct structured query against the free ClinicalTrials.gov REST API v2.
# No auth, no Playwright, no JavaScript rendering.
# Replaces the former BrightData Scraping Browser approach.

def fetch_clinicaltrials_api(
    pathway: str,
    drug: str = "",
    sponsor: str = "",
    max_results: int = 50,
) -> list[dict]:
    """
    Fetch active/recruiting ClinicalTrials.gov studies matching the pathway
    (and optionally drug/sponsor) via the free ClinicalTrials.gov API v2.

    No authentication or external proxy required.

    Each returned record has: source, nct_id, url, source_label, title,
    abstract (brief summary + phase + status + conditions), phase, status, conditions.
    Returns [] on any error so the pipeline is never blocked.
    """
    if not pathway and not drug and not sponsor:
        return []

    params: dict[str, Any] = {
        "format": "json",
        "pageSize": min(max_results, 100),
        "fields": (
            "NCTId,BriefTitle,OverallStatus,Phase,BriefSummary,"
            "ConditionsModule,ArmsInterventionsModule,LeadSponsorName"
        ),
        "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING",
    }
    if pathway:
        params["query.term"] = pathway
    if drug:
        params["query.intr"] = drug
    if sponsor:
        params["query.spons"] = sponsor

    results: list[dict] = []
    try:
        data = _ct_api_get(params)
        for study in data.get("studies", [])[:max_results]:
            ps = study.get("protocolSection", {})
            id_mod      = ps.get("identificationModule", {})
            status_mod  = ps.get("statusModule", {})
            desc_mod    = ps.get("descriptionModule", {})
            design_mod  = ps.get("designModule", {})
            cond_mod    = ps.get("conditionsModule", {})
            interv_mod  = ps.get("armsInterventionsModule", {})

            nct_id = id_mod.get("nctId", "")
            title  = id_mod.get("briefTitle", "")
            if not title:
                continue

            status = status_mod.get("overallStatus", "").replace("_", " ").title()
            phases = design_mod.get("phases", [])
            phase_str = ", ".join(
                p.replace("PHASE", "Phase ").replace("_", " ").title()
                for p in phases
            )
            conditions = cond_mod.get("conditions", [])
            cond_str = ", ".join(conditions[:5])
            brief_summary = desc_mod.get("briefSummary", "")

            # Build a rich abstract for the Synthesizer from structured fields
            abstract_parts = []
            if brief_summary:
                abstract_parts.append(brief_summary[:1500])
            if phase_str:
                abstract_parts.append(f"Phase: {phase_str}")
            if status:
                abstract_parts.append(f"Status: {status}")
            if cond_str:
                abstract_parts.append(f"Conditions: {cond_str}")

            interventions = [
                iv.get("name", "")
                for iv in interv_mod.get("interventions", [])
                if iv.get("name")
            ]
            if interventions:
                abstract_parts.append(f"Interventions: {', '.join(interventions[:5])}")

            results.append({
                "source": "clinicaltrials",
                "nct_id": nct_id,
                "url": f"https://clinicaltrials.gov/study/{nct_id}",
                "source_label": "ClinicalTrials.gov",
                "title": title,
                "abstract": ". ".join(abstract_parts) + "." if abstract_parts else "",
                "phase": phase_str,
                "status": status,
                "conditions": cond_str,
            })

        log.info(
            "ClinicalTrials API v2: %d studies fetched for pathway '%s'",
            len(results), pathway,
        )

    except Exception as e:
        log.warning(
            "ClinicalTrials API v2 fetch failed (%s: %s) — returning []",
            type(e).__name__, e,
        )

    return results


async def fetch_clinicaltrials_async(
    pathway: str,
    drug: str = "",
    sponsor: str = "",
    max_results: int = 50,
) -> list[dict]:
    """Async wrapper for fetch_clinicaltrials_api for use in ingest_all."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, fetch_clinicaltrials_api, pathway, drug, sponsor, max_results
    )


# ── 5. Catalyst Calendar — API v2 discovery + enrichment ─────────────────────
# Uses the free ClinicalTrials.gov API v2 to discover NCT IDs and retrieve
# authoritative structured dates (primaryCompletionDateStruct, startDateStruct)
# for each study. All catalyst fields are deterministic — no LLM involved.

def _parse_ct_date_struct(struct: Optional[dict]) -> tuple[str, str]:
    """Return (date_str as YYYY-MM-DD, type ACTUAL|ESTIMATED|'') from a CT date struct."""
    if not struct:
        return "", ""
    raw = struct.get("date", "")
    date_type = struct.get("type", "")
    if len(raw) == 7:
        raw = raw + "-01"
    return raw, date_type


def _readout_quarter(d: date) -> str:
    return f"Q{(d.month - 1) // 3 + 1} {d.year}"


@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def _ct_api_get(params: dict) -> dict:
    resp = requests.get(_CT_API_BASE, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def enrich_trials_via_api(nct_ids: list[str]) -> dict[str, dict]:
    """
    Fetch structured date / status / phase data for a list of NCT IDs from
    the ClinicalTrials.gov API v2 (free, no auth). Returns {} on any failure.
    Processes in chunks of 100 to respect URL length limits.
    """
    if not nct_ids:
        return {}

    enriched: dict[str, dict] = {}
    chunk_size = 100
    for i in range(0, len(nct_ids), chunk_size):
        chunk = nct_ids[i : i + chunk_size]
        try:
            data = _ct_api_get({
                "filter.ids": ",".join(chunk),
                "fields": _CT_FIELDS,
                "pageSize": len(chunk),
                "format": "json",
            })
        except Exception as e:
            log.warning("ClinicalTrials API v2 enrichment chunk %d failed: %s", i, e)
            continue

        for study in data.get("studies", []):
            ps = study.get("protocolSection", {})
            id_mod      = ps.get("identificationModule", {})
            status_mod  = ps.get("statusModule", {})
            design_mod  = ps.get("designModule", {})
            sponsor_mod = ps.get("sponsorCollaboratorsModule", {})
            interv_mod  = ps.get("armsInterventionsModule", {})
            cond_mod    = ps.get("conditionsModule", {})
            results_sec = study.get("resultsSection", {})

            nct_id = id_mod.get("nctId", "")
            if not nct_id:
                continue

            enriched[nct_id] = {
                "nct_id": nct_id,
                "title": id_mod.get("briefTitle", ""),
                "overall_status": status_mod.get("overallStatus", ""),
                "start_date_struct": status_mod.get("startDateStruct"),
                "primary_completion_date_struct": status_mod.get("primaryCompletionDateStruct"),
                "completion_date_struct": status_mod.get("completionDateStruct"),
                "results_first_post_date_struct": results_sec.get("resultsFirstPostDateStruct"),
                "phases": design_mod.get("phases", []),
                "lead_sponsor": sponsor_mod.get("leadSponsor", {}).get("name", ""),
                "interventions": [
                    iv.get("name", "")
                    for iv in interv_mod.get("interventions", [])
                    if iv.get("name")
                ],
                "conditions": cond_mod.get("conditions", []),
                "url": f"https://clinicaltrials.gov/study/{nct_id}",
            }

    log.info("ClinicalTrials API v2: enriched %d / %d NCT IDs", len(enriched), len(nct_ids))
    return enriched


def derive_catalysts(enriched: dict[str, dict]) -> list[dict]:
    """
    Compute days_until_readout, readout_window, and bucket for each study.

    Buckets (in display priority order):
      overdue  — past estimated primary completion, no results posted yet
      imminent — within 90 days, no results posted
      near     — 91–180 days out, no results posted
      upcoming — > 180 days or no date, no results posted
      reported — results already posted to ClinicalTrials.gov
    """
    today = date.today()
    catalysts: list[dict] = []

    for nct_id, study in enriched.items():
        pc_str, pc_type = _parse_ct_date_struct(study.get("primary_completion_date_struct"))
        start_str, _   = _parse_ct_date_struct(study.get("start_date_struct"))
        comp_str, _    = _parse_ct_date_struct(study.get("completion_date_struct"))
        results_struct  = study.get("results_first_post_date_struct")
        results_posted  = bool(results_struct and results_struct.get("date"))

        pc_date: Optional[date] = None
        try:
            if pc_str:
                pc_date = date.fromisoformat(pc_str)
        except ValueError:
            pass

        if pc_date:
            days_until: Optional[int] = (pc_date - today).days
            readout_window = _readout_quarter(pc_date)
        else:
            days_until = None
            readout_window = "TBD"

        if results_posted:
            bucket = "reported"
        elif days_until is None:
            bucket = "upcoming"
        elif days_until < 0:
            bucket = "overdue"
        elif days_until <= 90:
            bucket = "imminent"
        elif days_until <= 180:
            bucket = "near"
        else:
            bucket = "upcoming"

        phases = study.get("phases", [])
        phase_str = ", ".join(
            p.replace("PHASE", "Phase ").replace("_", " ").title()
            for p in phases
        )

        catalysts.append({
            "nct_id": nct_id,
            "title": study.get("title", ""),
            "url": study.get("url", f"https://clinicaltrials.gov/study/{nct_id}"),
            "lead_sponsor": study.get("lead_sponsor", ""),
            "phase": phase_str,
            "status": study.get("overall_status", "").replace("_", " ").title(),
            "interventions": study.get("interventions", []),
            "conditions": study.get("conditions", []),
            "start_date": start_str,
            "primary_completion_date": pc_str,
            "primary_completion_type": pc_type,
            "completion_date": comp_str,
            "readout_window": readout_window,
            "days_until_readout": days_until,
            "bucket": bucket,
            "results_posted": results_posted,
        })

    _bucket_order = {"overdue": 0, "imminent": 1, "near": 2, "upcoming": 3, "reported": 4}
    catalysts.sort(key=lambda c: (
        _bucket_order.get(c["bucket"], 5),
        c["days_until_readout"] if c["days_until_readout"] is not None else 9999,
    ))
    return catalysts


def fetch_trial_catalysts(
    pathway: str = "",
    drug: str = "",
    sponsor: str = "",
) -> list[dict]:
    """
    Discover NCT IDs via API v2, enrich with structured dates, derive catalysts.

    Uses the free ClinicalTrials.gov API v2 directly — no BrightData required.

    Returns a list of catalyst dicts (sorted overdue → imminent → near → upcoming → reported).
    Never raises — returns [] on complete failure.
    """
    if not pathway and not drug and not sponsor:
        return []

    nct_ids: list[str] = []
    try:
        params: dict[str, Any] = {
            "fields": _CT_FIELDS,
            "filter.overallStatus": (
                "RECRUITING,ACTIVE_NOT_RECRUITING,ENROLLING_BY_INVITATION"
            ),
            "pageSize": 50,
            "format": "json",
        }
        if pathway:
            params["query.term"] = pathway
        if drug:
            params["query.intr"] = drug
        if sponsor:
            params["query.spons"] = sponsor
        data = _ct_api_get(params)
        nct_ids = [
            study.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "")
            for study in data.get("studies", [])
        ]
        nct_ids = [n for n in nct_ids if n]
        log.info("Catalyst Calendar: API v2 discovered %d NCT IDs", len(nct_ids))
    except Exception as e:
        log.warning("Catalyst Calendar: API v2 query failed (%s) — returning []", e)
        return []

    enriched = enrich_trials_via_api(nct_ids)
    catalysts = derive_catalysts(enriched)
    log.info("Catalyst Calendar: %d catalyst records derived", len(catalysts))
    return catalysts


# ── 7. Conference Abstracts via BrightData Scraping Browser ──────────────────
# ACR  (acrabstracts.org)  — Green:  open robots.txt; search is server-rendered HTML;
#                                     BrightData adds bot-evasion resilience.
# ASCO (meetings.asco.org) — Red:    Flutter SPA; non-profit — BrightData may classify
#                                     as NGO; proxy_error is caught and returns [].
#
# Both return [] gracefully on any failure.
# Records (source, title, abstract, url, year) flow into the Synthesizer triage as
# plain text — no changes to ai_orchestrator.py are required.

_CONF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


async def _scrape_acr(
    pathway: str,
    drug: str = "",
    max_pages: int = 3,
) -> list[dict]:
    """
    Scrape ACR (American College of Rheumatology) abstracts from acrabstracts.org.
    acrabstracts.org robots.txt is fully open (Disallow: nothing).
    Search results load as server-rendered HTML; BrightData provides bot evasion
    and renders any lazy-loaded pagination JS.

    Up to max_pages of search results are collected; each unique abstract slug is
    then visited for the full title + body text.
    """
    auth = os.getenv("BRIGHTDATA_BROWSER_AUTH")
    if not auth:
        return []

    import urllib.parse
    from playwright.async_api import async_playwright

    query = urllib.parse.quote(" ".join(p for p in [pathway, drug] if p))
    ws_url = f"wss://{auth}@brd.superproxy.io:9222"
    current_year = str(date.today().year)
    results: list[dict] = []
    seen_urls: set[str] = set()

    try:
        async with async_playwright() as p:
            log.info("ACR: connecting to BrightData Scraping Browser...")
            browser = await asyncio.wait_for(
                p.chromium.connect_over_cdp(ws_url), timeout=60
            )
            log.info("ACR: connected, starting search...")
            page = await browser.new_page()

            for page_num in range(1, max_pages + 1):
                search_url = (
                    f"https://acrabstracts.org/?s={query}"
                    if page_num == 1
                    else f"https://acrabstracts.org/page/{page_num}/?s={query}"
                )
                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
                    log.info("ACR: search page %d loaded", page_num)
                except Exception as e:
                    log.warning("ACR: search page %d failed (%s)", page_num, e)
                    break

                links: list[str] = await page.evaluate("""
                    () => [...new Set(
                        Array.from(document.querySelectorAll('a[href*="/abstract/"]'))
                            .map(a => a.href)
                            .filter(h => h.includes('acrabstracts.org/abstract/'))
                    )]
                """) or []
                log.info("ACR: found %d abstract links on page %d", len(links), page_num)

                new_links = [l for l in links if l not in seen_urls]
                if not new_links:
                    break
                seen_urls.update(new_links)

                for abs_url in new_links[:20]:
                    try:
                        await page.goto(abs_url, wait_until="domcontentloaded", timeout=40_000)
                        data = await page.evaluate("""
                            () => {
                                const titleEl = (
                                    document.querySelector('.entry-title') ||
                                    document.querySelector('h1')           ||
                                    document.querySelector('h2')
                                );
                                const title = titleEl ? titleEl.textContent.trim() : '';
                                const bodyEl = (
                                    document.querySelector('.entry-content')    ||
                                    document.querySelector('.abstract-content') ||
                                    document.querySelector('article .content')  ||
                                    document.querySelector('.abstract')
                                );
                                const body = bodyEl ? bodyEl.textContent.trim() : '';
                                const yearM = (document.title + document.body.textContent)
                                                .match(/20\\d{2}/);
                                return { title, body, year: yearM ? yearM[0] : '' };
                            }
                        """)
                        title    = (data.get("title") or "").strip()
                        abstract = (data.get("body")  or "").strip()
                        rec_year = (data.get("year")  or current_year).strip()[:4]
                        if title and abstract:
                            results.append({
                                "source": "acr",
                                "source_label": f"ACR {rec_year}",
                                "title": title,
                                "abstract": abstract[:3000],
                                "url": abs_url,
                                "year": rec_year,
                            })
                    except Exception as e:
                        log.debug("ACR: skipping %s (%s)", abs_url, e)

            await browser.close()

    except asyncio.TimeoutError:
        log.warning("ACR: BrightData connection timed out")
    except Exception as e:
        log.warning("ACR scrape failed (%s: %s) — returning %d collected", type(e).__name__, e, len(results))

    log.info("ACR: scraped %d abstracts for '%s'", len(results), pathway)
    return results



async def _scrape_asco(
    pathway: str,
    drug: str = "",
    year: Optional[int] = None,
) -> list[dict]:
    """
    Scrape ASCO (American Society of Clinical Oncology) abstracts from
    meetings.asco.org, a Flutter SPA that requires BrightData for JS rendering.

    ASCO is a non-profit and may be classified as an NGO by BrightData, which
    blocks such sites by default. A proxy_error is caught and returns [] with an
    informative log message. To unlock: submit KYC at brightdata.com compliance.
    """
    auth = os.getenv("BRIGHTDATA_BROWSER_AUTH")
    if not auth:
        return []

    from playwright.async_api import async_playwright

    ws_url   = f"wss://{auth}@brd.superproxy.io:9222"
    query    = " ".join(p for p in [pathway, drug] if p)
    rec_year = str(year or date.today().year)
    results: list[dict] = []

    try:
        async with async_playwright() as p:
            log.info("ASCO: connecting to BrightData Scraping Browser...")
            browser = await asyncio.wait_for(
                p.chromium.connect_over_cdp(ws_url), timeout=30
            )
            page = await browser.new_page()

            await page.goto(
                "https://meetings.asco.org/abstracts-presentations/search",
                wait_until="networkidle",
                timeout=60_000,
            )
            await page.wait_for_timeout(3000)  # Flutter needs extra settle time

            # Locate search input in the Flutter DOM
            search_input = None
            for sel in [
                'input[type="search"]',
                'input[placeholder*="earch"]',
                'input[aria-label*="earch"]',
                '[role="searchbox"]',
                'input[type="text"]',
            ]:
                try:
                    el = await page.wait_for_selector(sel, timeout=4000)
                    if el:
                        search_input = el
                        break
                except Exception:
                    continue

            if not search_input:
                log.warning("ASCO: search input not found after render — returning []")
                await browser.close()
                return []

            await search_input.fill(query)
            await search_input.press("Enter")
            await page.wait_for_timeout(4000)

            abstracts = await page.evaluate("""
                () => {
                    const cards = document.querySelectorAll(
                        '[class*="abstract-card"], [class*="result-item"], ' +
                        '[class*="search-result"], article, [role="article"]'
                    );
                    return Array.from(cards).map(card => {
                        const titleEl = card.querySelector('h2, h3, [class*="title"]');
                        const bodyEl  = card.querySelector('p, [class*="body"], [class*="abstract"]');
                        const linkEl  = card.querySelector('a[href]');
                        return {
                            title: titleEl ? titleEl.textContent.trim() : '',
                            body:  bodyEl  ? bodyEl.textContent.trim()  : '',
                            href:  linkEl  ? linkEl.href : '',
                        };
                    }).filter(c => c.title);
                }
            """) or []

            await browser.close()

            for card in abstracts[:40]:
                title    = (card.get("title") or "").strip()
                abstract = (card.get("body")  or "").strip()
                url      = card.get("href") or "https://meetings.asco.org/abstracts-presentations/search"
                if title:
                    results.append({
                        "source": "asco",
                        "source_label": f"ASCO {rec_year}",
                        "title": title,
                        "abstract": abstract[:3000],
                        "url": url,
                        "year": rec_year,
                    })

    except asyncio.TimeoutError:
        log.warning("ASCO: BrightData connection timed out")
    except Exception as e:
        err = str(e)
        if "proxy_error" in err or "Access denied" in err or "classified as" in err:
            log.warning(
                "ASCO: blocked by BrightData (NGO classification) — returning []. "
                "To unlock, submit KYC at https://brightdata.com/acceptable-use-policy"
            )
        else:
            log.warning("ASCO scrape failed (%s: %s) — returning []", type(e).__name__, e)

    log.info("ASCO: scraped %d abstracts for '%s'", len(results), query)
    return results


async def fetch_conference_abstracts(
    pathway: str = "",
    drug: str = "",
    conferences: Optional[List[str]] = None,
) -> list[dict]:
    """
    Orchestrate BrightData conference abstract scraping for the given conference list.
    conferences: subset of ["acr", "asco"] — only listed ones run.

    Scrapers run concurrently; each failure is logged and returns [] without
    blocking the others. Returns [] immediately if BRIGHTDATA_BROWSER_AUTH is unset.
    """
    if not os.getenv("BRIGHTDATA_BROWSER_AUTH"):
        log.info("BRIGHTDATA_BROWSER_AUTH not set — conference abstract agent returning []")
        return []

    enabled = set(conferences or [])
    if not enabled:
        return []

    scraper_map = {
        "acr":  lambda: _scrape_acr(pathway, drug),
        "asco": lambda: _scrape_asco(pathway, drug),
    }
    active = [(k, scraper_map[k]) for k in ("acr", "asco") if k in enabled]
    if not active:
        return []

    gathered = await asyncio.gather(
        *[fn() for _, fn in active],
        return_exceptions=True,
    )

    all_records: list[dict] = []
    for (conf, _), result in zip(active, gathered):
        if isinstance(result, Exception):
            log.warning("Conference scraper '%s' raised unexpectedly: %s", conf, result)
        elif isinstance(result, list):
            all_records.extend(result)

    log.info("Conference abstracts total: %d records from %s", len(all_records), list(enabled))
    return all_records


# ── 6. ChemRxiv (stretch goal — preclinical pharmacology) ────────────────────

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
    include_pubmed: bool = False,
    include_openalex: bool = False,
    include_chemrxiv: bool = False,
    include_clinicaltrials: bool = False,
    drug: str = "",
    sponsor: str = "",
    conference_list: Optional[List[str]] = None,
) -> list[dict]:
    """
    Run all ingestion agents and return a unified list of text records.
    Each record has at minimum: source, title/text, abstract/body.

    include_pubmed         — fetch peer-reviewed PubMed abstracts via NCBI E-utilities.
    include_openalex       — annotate DOI-bearing preprints with OpenAlex citation counts.
    include_clinicaltrials — fetch ClinicalTrials.gov text records via API v2
                             (no BrightData required).
    conference_list        — list of conference keys to scrape, e.g. ["acr", "asco"].
                             Silently no-ops if BRIGHTDATA_BROWSER_AUTH is not set.
    drug / sponsor         — optional filters threaded into ClinicalTrials searches.

    NOTE: Catalyst Calendar structured records (dates, readout windows) come from
    fetch_trial_catalysts(), called separately in app.py as cached_catalysts().
    """
    subreddits = reddit_subreddits or ["biotech", "investing", "stocks"]

    loop = asyncio.get_event_loop()

    reddit_tasks = [extract_reddit_playwright(sub, 50) for sub in subreddits]
    preprint_task = fetch_all_preprints(days_back)
    twitter_task = loop.run_in_executor(
        None, fetch_x_kol_grok, twitter_handles or [], pathway_hint, days_back
    )

    # PubMed peer-reviewed literature via NCBI E-utilities
    run_pubmed = include_pubmed and bool(pathway_hint)
    if run_pubmed:
        pubmed_task: asyncio.Future = asyncio.ensure_future(
            fetch_pubmed_literature_async(pathway_hint, days_back=days_back)
        )

    # ClinicalTrials.gov via API v2 — no BrightData required
    run_ct = include_clinicaltrials and bool(pathway_hint or drug)
    if run_ct:
        ct_task: asyncio.Future = asyncio.ensure_future(
            fetch_clinicaltrials_async(pathway_hint, drug=drug, sponsor=sponsor)
        )

    # Conference abstracts still use BrightData
    has_brightdata = bool(os.getenv("BRIGHTDATA_BROWSER_AUTH"))
    run_conf = bool(conference_list) and has_brightdata
    if run_conf:
        conf_task: asyncio.Future = asyncio.ensure_future(
            fetch_conference_abstracts(pathway_hint, drug=drug, conferences=conference_list)
        )

    gather_results = await asyncio.gather(
        asyncio.gather(*reddit_tasks, return_exceptions=True),
        preprint_task,
        twitter_task,
        return_exceptions=False,
    )
    reddit_results, preprint_results, twitter_results = gather_results

    all_records: list[dict] = []
    for result in reddit_results:
        if isinstance(result, list):
            all_records.extend(result)

    if include_openalex:
        preprint_results = await annotate_openalex_citations_async(preprint_results)

    all_records.extend(preprint_results)
    all_records.extend(twitter_results)

    if run_pubmed:
        pubmed_records = await pubmed_task
        all_records.extend(pubmed_records)

    if run_ct:
        ct_records = await ct_task
        all_records.extend(ct_records)

    if run_conf:
        conf_records = await conf_task
        all_records.extend(conf_records)

    if include_chemrxiv:
        chemrxiv_results = await loop.run_in_executor(None, fetch_chemrxiv, days_back)
        if include_openalex:
            chemrxiv_results = await annotate_openalex_citations_async(chemrxiv_results)
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
