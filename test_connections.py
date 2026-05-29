"""
PathwayPulse — API Connection Smoke Tests
Run this before building any pipeline logic to verify all API credentials work.
Usage: python test_connections.py
"""
import asyncio
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"
WARN = "\033[93m⚠ WARN\033[0m"
SKIP = "\033[94m– SKIP\033[0m"


# ── 1. AI/ML API (DeepSeek-V3 via OpenAI-compatible SDK) ─────────────────────

async def test_aimlapi() -> bool:
    print("\n[1/5] AI/ML API (DeepSeek-V3) ...")
    key = os.getenv("AIMLAPI_KEY")
    if not key:
        print(f"  {FAIL}  AIMLAPI_KEY not set in .env")
        return False
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(base_url="https://api.aimlapi.com/v1", api_key=key)
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="deepseek/deepseek-chat-v3-0324",
                messages=[{"role": "user", "content": "Ping. Reply with: pong"}],
                max_tokens=10,
            ),
            timeout=30,
        )
        reply = resp.choices[0].message.content.strip()
        print(f"  {PASS}  Model replied: {reply!r}")
        return True
    except TimeoutError:
        print(f"  {FAIL}  Request timed out after 30s")
    except Exception as e:
        code = getattr(e, 'status_code', None) or getattr(getattr(e, 'response', None), 'status_code', None)
        if code in (401, 403):
            print(f"  {FAIL}  Auth error ({code}) — check your AIMLAPI_KEY")
        else:
            print(f"  {FAIL}  {type(e).__name__}: {e}")
    return False


# ── 2. Bright Data Scraping Browser ──────────────────────────────────────────

async def test_brightdata() -> bool:
    print("\n[2/5] Bright Data Scraping Browser ...")
    auth = os.getenv("BRIGHTDATA_BROWSER_AUTH")
    if not auth:
        print(f"  {FAIL}  BRIGHTDATA_BROWSER_AUTH not set in .env")
        return False

    from playwright.async_api import async_playwright

    browser = None
    try:
        async with async_playwright() as p:
            ws_url = f"wss://{auth}@brd.superproxy.io:9222"
            browser = await asyncio.wait_for(
                p.chromium.connect_over_cdp(ws_url),
                timeout=30,
            )
            page = await browser.new_page()
            resp = await asyncio.wait_for(
                page.goto("http://lumtest.com/myip.json"),
                timeout=30,
            )
            body = await page.inner_text("pre") if await page.query_selector("pre") else await page.content()
            print(f"  {PASS}  Connected via proxy. Response snippet: {body[:120].strip()}")
            return True
    except TimeoutError:
        print(f"  {FAIL}  Connection timed out after 30s — check BRIGHTDATA_BROWSER_AUTH")
    except Exception as e:
        msg = str(e)
        if "401" in msg or "403" in msg or "Unauthorized" in msg:
            print(f"  {FAIL}  Auth error — verify BRIGHTDATA_BROWSER_AUTH credentials")
        else:
            print(f"  {FAIL}  {type(e).__name__}: {e}")
    finally:
        if browser:
            await browser.close()
    return False


# ── 3. Reddit RSS Feed (no auth required) ────────────────────────────────────

def test_reddit_scrape() -> bool:
    print("\n[3/5] Reddit Atom RSS feed (r/biotech) ...")
    import xml.etree.ElementTree as ET
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PathwayPulse/1.0)"}
        resp = requests.get(
            "https://www.reddit.com/r/biotech/new.rss?limit=5",
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 429:
            print(f"  {WARN}  Rate-limited by Reddit — wait 60s and retry (transient)")
            return True
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        entries = root.findall("atom:entry", ns)
        if not entries:
            print(f"  {WARN}  RSS feed parsed but returned 0 entries")
            return True
        print(f"  {PASS}  Fetched {len(entries)} entries from r/biotech RSS:")
        for i, e in enumerate(entries[:3], 1):
            title = e.findtext("atom:title", default="(no title)", namespaces=ns)
            print(f"    {i}. {title[:90]}")
        return True
    except requests.exceptions.Timeout:
        print(f"  {FAIL}  Request timed out")
        return False
    except Exception as e:
        print(f"  {FAIL}  {type(e).__name__}: {e}")
        return False


# ── 4. bioRxiv + medRxiv REST APIs ───────────────────────────────────────────

def test_preprint_apis() -> bool:
    print("\n[4/5] bioRxiv + medRxiv REST APIs ...")
    from datetime import date, timedelta
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=1)).isoformat()
    all_ok = True
    for server in ("biorxiv", "medrxiv"):
        url = f"https://api.biorxiv.org/details/{server}/{start}/{end}/0"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            count = len(data.get("collection", []))
            print(f"  {PASS}  {server}: {count} records returned for {start}")
        except requests.exceptions.Timeout:
            print(f"  {FAIL}  {server}: request timed out")
            all_ok = False
        except Exception as e:
            print(f"  {FAIL}  {server}: {type(e).__name__}: {e}")
            all_ok = False
    return all_ok


# ── 5. Grok x_search / KOL Twitter ingestion (optional) ──────────────────────

def test_grok_xsearch() -> bool:
    print("\n[5/5] Grok xAI x_search — KOL Twitter ingestion (optional) ...")
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        print(f"  {SKIP}  XAI_API_KEY not set — KOL Twitter ingestion disabled (add key to .env to enable)")
        return True
    try:
        from datetime import date, timedelta
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        response = client.responses.create(
            model="grok-3-latest",
            input=[{"role": "user", "content": "Return one recent public post from this account as a JSON object with keys: handle, text, url. No markdown."}],
            tools=[{
                "type": "x_search",
                "allowed_x_handles": ["BioPharmaDive"],
                "from_date": yesterday,
            }],
        )

        raw = ""
        for item in response.output:
            if hasattr(item, "content"):
                for block in item.content:
                    if hasattr(block, "text"):
                        raw += block.text

        if raw.strip():
            print(f"  {PASS}  Grok x_search reachable. Response snippet: {raw.strip()[:120]}")
            return True

        print(f"  {WARN}  Grok responded but returned no text content — x_search may have found no posts")
        return True

    except Exception as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg:
            print(f"  {FAIL}  XAI_API_KEY is invalid — check your key at console.x.ai")
            return False
        elif "403" in msg or "Forbidden" in msg:
            print(f"  {FAIL}  Access denied — verify your xAI account has API access enabled")
            return False
        else:
            print(f"  {WARN}  {type(e).__name__}: {e} — KOL agent will return [] at runtime")
    return True


# ── Runner ────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("  PathwayPulse — API Connection Tests")
    print("=" * 60)

    results = {}
    results["aimlapi"] = await test_aimlapi()
    results["brightdata"] = await test_brightdata()
    results["reddit_scrape"] = test_reddit_scrape()
    results["preprints"] = test_preprint_apis()
    results["twitter"] = test_grok_xsearch()

    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    critical = ["aimlapi", "brightdata", "reddit_scrape", "preprints"]
    all_critical_ok = all(results[k] for k in critical)
    for name, ok in results.items():
        label = PASS if ok else (SKIP if name == "twitter" else FAIL)
        tag = "(optional)" if name == "twitter" else "(required)"
        display = name.replace("_", " ")
        print(f"  {label}  {display} {tag}")

    print()
    if all_critical_ok:
        print("  \033[92mAll required APIs connected. Ready to build the swarm.\033[0m")
        sys.exit(0)
    else:
        print("  \033[91mOne or more required APIs failed. Fix credentials before proceeding.\033[0m")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
