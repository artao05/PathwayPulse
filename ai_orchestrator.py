"""
PathwayPulse — AI Orchestration (Dual-Model Pipeline)

Synthesizer  →  DeepSeek-V3 via AI/ML API  (high-throughput triage, cheap)
Executioner  →  gpt-4o via OpenAI           (deep immunological reasoning)

Flow:
  raw records  →  triage_data_batch()  →  [CrossPollinationEvent]
               →  generate_arbitrage_report()  →  markdown report
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

log = logging.getLogger(__name__)
ERROR_LOG = Path("errors.log")


# ── Pydantic Schema ───────────────────────────────────────────────────────────

class CrossPollinationEvent(BaseModel):
    baseline_pathway: str = Field(description="The biological pathway being tracked (e.g. 'IL-6 signaling')")
    original_indication: str = Field(description="The established therapeutic area where this pathway is already used")
    novel_indication: str = Field(description="The unexpected new therapeutic area where the pathway is being applied")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Confidence that this is a genuine cross-pollination signal (0–1)")
    source_evidence: str = Field(description="The specific text excerpt or data point that triggered this detection")


class TriageResult(BaseModel):
    events: list[CrossPollinationEvent]
    is_relevant: bool = Field(description="True if any cross-pollination signal was detected")


# ── Synthesizer (DeepSeek-V3 via AI/ML API) ───────────────────────────────────

def _make_synthesizer_client():
    from openai import AsyncOpenAI
    key = os.getenv("AIMLAPI_KEY")
    if not key:
        raise RuntimeError("AIMLAPI_KEY not set — cannot run Synthesizer")
    return AsyncOpenAI(base_url="https://api.aimlapi.com/v1", api_key=key)


_SYNTHESIZER_SYSTEM = """\
You are a biotech intelligence analyst specializing in biological pathway cross-pollination.
Your task: given a text excerpt and a target biological pathway, determine if the text contains
evidence that this pathway is being applied to a NEW or UNEXPECTED therapeutic indication
beyond its established use.

You MUST respond with ONLY a valid JSON object — no markdown, no explanation, no code fences.
Use this exact structure:

{
  "is_relevant": true or false,
  "events": [
    {
      "baseline_pathway": "the pathway name",
      "original_indication": "the established disease area where this pathway is known",
      "novel_indication": "the new or unexpected disease area detected in this text",
      "confidence_score": 0.0 to 1.0,
      "source_evidence": "the specific sentence or phrase that triggered this detection"
    }
  ]
}

If no cross-pollination signal is detected, return {"is_relevant": false, "events": []}.
Be rigorous: only flag genuine mechanistic cross-indication signals, not general mentions.
"""


async def _triage_single(
    client,
    record: dict,
    pathway: str,
    semaphore: asyncio.Semaphore,
) -> TriageResult | None:
    """Triage one record. Returns None on failure (logged to errors.log)."""
    text = record.get("abstract") or record.get("body") or record.get("text") or ""
    title = record.get("title") or record.get("text", "")[:80]
    if not text.strip():
        return None

    prompt = (
        f"Biological pathway under investigation: {pathway}\n\n"
        f"Source: {record.get('source', 'unknown')}\n"
        f"Title: {title}\n\n"
        f"Text:\n{text[:3000]}"
    )

    async with semaphore:
        try:
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model="deepseek/deepseek-chat-v3-0324",
                    messages=[
                        {"role": "system", "content": _SYNTHESIZER_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=512,
                    temperature=0.1,
                ),
                timeout=45,
            )
            raw = resp.choices[0].message.content

            # Strip accidental markdown code fences if the model adds them
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            parsed = TriageResult.model_validate_json(raw)
            return parsed
        except ValidationError as e:
            _log_error(f"Schema validation error for record '{title[:60]}': {e}")
        except asyncio.TimeoutError:
            _log_error(f"Timeout triaging record '{title[:60]}'")
        except Exception as e:
            _log_error(f"Synthesizer error for record '{title[:60]}': {type(e).__name__}: {e}")
    return None


def _log_error(msg: str):
    log.warning(msg)
    with ERROR_LOG.open("a") as f:
        f.write(msg + "\n")


async def triage_data_batch(
    records: list[dict],
    pathway: str,
    concurrency: int = 10,
) -> list[CrossPollinationEvent]:
    """
    Run the Synthesizer over a batch of ingested records.
    Uses asyncio.gather with return_exceptions=True — failures are logged and skipped.
    concurrency limits parallel API calls to protect rate limits.
    """
    if not records:
        return []

    client = _make_synthesizer_client()
    semaphore = asyncio.Semaphore(concurrency)

    tasks = [_triage_single(client, record, pathway, semaphore) for record in records]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    events: list[CrossPollinationEvent] = []
    for r in results:
        if isinstance(r, Exception):
            _log_error(f"Unexpected gather exception: {r}")
            continue
        if r is None or not r.is_relevant:
            continue
        events.extend(r.events)

    log.info(
        "Synthesizer: %d records → %d CrossPollinationEvents detected",
        len(records),
        len(events),
    )
    return events


# ── Executioner (gpt-4o via standard OpenAI) ──────────────────────────────────

_EXECUTIONER_SYSTEM = """\
You are a senior biotech analyst with deep expertise in immunology, oncology, and drug
repurposing strategy. You have been given a set of detected biological pathway
cross-pollination signals, each with a confidence score and source evidence.

Your task: write a concise, rigorous arbitrage intelligence report in Markdown.

Structure your report as follows:
1. **Verdict** — Overall Bear / Bull / Neutral on this pathway's cross-indication opportunity
2. **Immunological Soundness** — Evaluate whether the detected novel indications are
   mechanistically plausible given the pathway's biology
3. **Signal Quality** — Rank the top signals by confidence and explain what makes each
   credible or speculative
4. **Risk Factors** — What could invalidate these signals (competing pathways, trial failures,
   regulatory hurdles)?
5. **Watch List** — Specific companies, trials, or papers to monitor

Be direct. Use scientific terminology. Do not hedge excessively.
"""


def generate_arbitrage_report(
    events: list[CrossPollinationEvent],
    pathway: str,
    model: str = "gpt-4o",
) -> str:
    """
    Generate a Bear/Bull/Neutral arbitrage report from detected CrossPollinationEvents.
    Routes to gpt-4o (or o1 if specified) via standard OpenAI.
    Returns a markdown string.
    """
    if not events:
        return (
            f"## PathwayPulse Report — {pathway}\n\n"
            "**Verdict: Neutral**\n\n"
            "No cross-pollination signals detected in the current data window. "
            "Consider expanding `days_back` or adding more data sources."
        )

    from openai import OpenAI
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set — cannot run Executioner")
    client = OpenAI(api_key=key)

    events_payload = json.dumps(
        [e.model_dump() for e in events],
        indent=2,
    )
    user_prompt = (
        f"Biological pathway: {pathway}\n\n"
        f"Detected CrossPollinationEvents ({len(events)} total):\n```json\n{events_payload}\n```\n\n"
        "Write the arbitrage intelligence report now."
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _EXECUTIONER_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1500,
            temperature=0.3,
        )
        report = resp.choices[0].message.content
        log.info("Executioner: report generated (%d chars, model=%s)", len(report), model)
        return report
    except Exception as e:
        log.error("Executioner failed: %s", e)
        return f"## Report Generation Failed\n\n```\n{e}\n```"


# ── Full Pipeline Convenience Function ───────────────────────────────────────

async def run_pipeline(
    records: list[dict],
    pathway: str,
    executioner_model: str = "gpt-4o",
    concurrency: int = 10,
) -> tuple[list[CrossPollinationEvent], str]:
    """
    Run the complete dual-model pipeline:
      records → Synthesizer → events → Executioner → report
    Returns (events, markdown_report).
    """
    events = await triage_data_batch(records, pathway, concurrency=concurrency)
    report = generate_arbitrage_report(events, pathway, model=executioner_model)
    return events, report


# ── Demo ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sample_records = [
        {
            "source": "biorxiv",
            "title": "IL-6 trans-signaling drives pathogenic Th17 differentiation in lupus nephritis",
            "abstract": (
                "We demonstrate that IL-6 trans-signaling via soluble IL-6 receptor selectively "
                "expands pathogenic Th17 cells in murine lupus models, distinct from its canonical "
                "role in hepatic acute-phase responses seen in oncology cachexia. Tocilizumab, "
                "previously approved for rheumatoid arthritis and cytokine release syndrome, "
                "showed potent efficacy in reducing anti-dsDNA titers and improving renal function "
                "in a phase 2 SLE trial. This suggests IL-6 pathway blockade may represent a "
                "novel therapeutic angle in systemic lupus beyond its established oncologic utility."
            ),
        },
        {
            "source": "reddit",
            "title": "$ABBV - AbbVie IL-6 data in Crohn's looks interesting",
            "body": (
                "Just read the abstract from UEGW. Their IL-6 inhibitor showed 40% remission rate "
                "in biologic-naive Crohn's patients. Nobody is talking about this. The mechanism "
                "makes sense — mucosal IL-6 is a major driver of intestinal inflammation. "
                "If the phase 3 data holds this could be massive for the IBD indication."
            ),
        },
        {
            "source": "medrxiv",
            "title": "Repurposing JAK-STAT pathway inhibitors for fibrotic lung disease",
            "abstract": (
                "Ruxolitinib and baricitinib, JAK1/2 inhibitors developed for myelofibrosis and "
                "rheumatoid arthritis, demonstrated significant reduction in fibroblast activation "
                "and TGF-β expression in IPF patient-derived samples. A retrospective cohort study "
                "of 84 IPF patients receiving off-label JAK inhibition showed 31% reduction in "
                "FVC decline over 12 months. These findings position JAK-STAT inhibition as an "
                "emerging mechanistic target in pulmonary fibrosis."
            ),
        },
    ]

    async def _demo():
        print("Running PathwayPulse pipeline demo (IL-6 signaling)...\n")
        events, report = await run_pipeline(sample_records, "IL-6 signaling")
        print(f"Events detected: {len(events)}")
        for ev in events:
            print(f"  → {ev.original_indication} → {ev.novel_indication} (confidence: {ev.confidence_score:.2f})")
        print("\n--- ARBITRAGE REPORT ---\n")
        print(report)

    asyncio.run(_demo())
