"""
PathwayPulse — Arbitrage Matrix Dashboard
Streamlit app with a dynamic node graph (streamlit-flow) and AI-generated report.
"""
import asyncio
import os

import streamlit as st
from dotenv import load_dotenv
from streamlit_flow import streamlit_flow
from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
from streamlit_flow.layouts import TreeLayout
from streamlit_flow.state import StreamlitFlowState

from ai_orchestrator import CrossPollinationEvent, run_pipeline
from swarm_ingestion import ingest_all

load_dotenv()

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PathwayPulse",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 800;
        letter-spacing: -0.5px;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 0.95rem;
        color: #888;
        margin-top: 0;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background: #1a1a2e;
        border-radius: 10px;
        padding: 1rem 1.25rem;
        border: 1px solid #2d2d4e;
    }
    .signal-high { color: #e63946; font-weight: 700; }
    .signal-low  { color: #aaa; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Cached ingestion wrappers ─────────────────────────────────────────────────
# @st.cache_data ensures that interacting with the node graph (which re-runs
# the script) never re-triggers the scrapers or AI APIs.

@st.cache_data(ttl=3600, show_spinner=False)
def cached_ingest(
    pathway: str,
    days_back: int,
    include_chemrxiv: bool,
    kol_handles: tuple,          # tuple (not list) so @st.cache_data can hash it
) -> list[dict]:
    return asyncio.run(
        ingest_all(
            pathway_hint=pathway,
            reddit_subreddits=["biotech", "investing", "stocks"],
            twitter_handles=list(kol_handles),
            days_back=days_back,
            include_chemrxiv=include_chemrxiv,
        )
    )


@st.cache_data(ttl=3600, show_spinner=False)
def cached_pipeline(
    pathway: str,
    days_back: int,
    include_chemrxiv: bool,
    kol_handles: tuple,
    model: str,
) -> tuple[list[dict], str]:
    records = cached_ingest(pathway, days_back, include_chemrxiv, kol_handles)
    events, report = asyncio.run(
        run_pipeline(records, pathway, executioner_model=model)
    )
    return [e.model_dump() for e in events], report


# ── Node graph builder ────────────────────────────────────────────────────────

def _build_flow_state(
    pathway: str,
    events: list[CrossPollinationEvent],
) -> StreamlitFlowState:
    nodes: list[StreamlitFlowNode] = []
    edges: list[StreamlitFlowEdge] = []

    # Central root node
    nodes.append(
        StreamlitFlowNode(
            id="root",
            pos=(0, 0),
            data={"content": f"🔬 {pathway}"},
            node_type="input",
            style={
                "background": "#1e3a5f",
                "color": "#ffffff",
                "border": "2px solid #4a90d9",
                "borderRadius": "12px",
                "padding": "10px 18px",
                "fontWeight": "700",
                "fontSize": "14px",
                "minWidth": "180px",
            },
        )
    )

    # Group events by novel indication to avoid duplicate child nodes
    seen_indications: dict[str, float] = {}
    for ev in events:
        key = ev.novel_indication.lower().strip()
        if key not in seen_indications or ev.confidence_score > seen_indications[key]:
            seen_indications[key] = ev.confidence_score

    for idx, (indication, confidence) in enumerate(seen_indications.items()):
        node_id = f"node_{idx}"
        is_high = confidence >= 0.5

        # Find best matching event for label details
        best_ev = max(
            (e for e in events if e.novel_indication.lower().strip() == indication),
            key=lambda e: e.confidence_score,
        )

        label = f"{'🔴' if is_high else '⚪'} {best_ev.novel_indication}"
        conf_pct = f"{confidence:.0%}"

        nodes.append(
            StreamlitFlowNode(
                id=node_id,
                pos=(0, 0),
                data={
                    "content": f"{label}\n({conf_pct} confidence)\n↩ from {best_ev.original_indication}",
                },
                node_type="default",
                style={
                    "background": "#3d1a1a" if is_high else "#1e1e2e",
                    "color": "#ffffff",
                    "border": f"2px solid {'#e63946' if is_high else '#444'}",
                    "borderRadius": "10px",
                    "padding": "8px 14px",
                    "fontSize": "12px",
                    "maxWidth": "220px",
                    "whiteSpace": "pre-wrap",
                },
            )
        )

        edges.append(
            StreamlitFlowEdge(
                id=f"edge_{idx}",
                source="root",
                target=node_id,
                animated=is_high,
                style={
                    "stroke": "#e63946" if is_high else "#555",
                    "strokeWidth": 3 if is_high else 1.5,
                },
                label=conf_pct if is_high else "",
                marker_end={"type": "arrowclosed", "color": "#e63946" if is_high else "#555"},
            )
        )

    return StreamlitFlowState(nodes=nodes, edges=edges)


# ── Sidebar — Thesis Control Center ──────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🎯 Thesis Control Center")
    st.markdown("---")

    pathway_input = st.text_input(
        "Biological Pathway",
        value="IL-6 signaling",
        placeholder="e.g. JAK-STAT, CRISPR base editing, PD-L1 ...",
        help="The pathway you want to track across therapeutic areas.",
    )

    st.markdown("**Data Sources**")
    days_back = st.slider("Days of preprint history", min_value=1, max_value=14, value=3)
    include_chemrxiv = st.checkbox("Include ChemRxiv (preclinical)", value=False)

    st.markdown("**X / Twitter KOL Handles** (optional)")

    # Load default handles from kol_handles.json if present
    _default_handles: list[str] = []
    try:
        import json as _json, pathlib as _pathlib
        _kol_path = _pathlib.Path(__file__).parent / "kol_handles.json"
        if _kol_path.exists():
            _default_handles = _json.loads(_kol_path.read_text()).get("handles", [])
    except Exception:
        pass

    kol_input = st.text_area(
        "One handle per line or comma-separated",
        value="\n".join(_default_handles),
        placeholder="EricTopol\nBioPharmaDive\nAdamFeuerstein",
        height=100,
        help=(
            "Grok searches recent public posts from these accounts for pathway signals. "
            "Requires XAI_API_KEY in .env. Max 20 handles — extras are ignored."
        ),
    )
    kol_handles: tuple = tuple(
        h.strip().lstrip("@")
        for h in kol_input.replace(",", "\n").splitlines()
        if h.strip()
    )

    if kol_handles and not os.getenv("XAI_API_KEY"):
        st.caption("⚠ XAI_API_KEY not set — X/Twitter ingestion disabled")

    st.markdown("**AI Executioner Model**")
    model_choice = st.selectbox(
        "Report model",
        options=["gpt-4o", "o1"],
        index=0,
        help="gpt-4o is faster and cheaper; o1 provides deeper reasoning.",
    )

    st.markdown("---")
    run_btn = st.button("⚡ Run Analysis", use_container_width=True, type="primary")

    st.markdown("---")
    st.markdown(
        "**Signal Legend**\n"
        "- 🔴 High confidence (≥50%)\n"
        "- ⚪ Weak / speculative (<50%)\n"
        "- Crimson pulsing edge = strong signal\n"
    )

    if st.button("🗑 Clear Cache", use_container_width=True):
        cached_ingest.clear()
        cached_pipeline.clear()
        if "flow_state" in st.session_state:
            del st.session_state["flow_state"]
        if "pipeline_results" in st.session_state:
            del st.session_state["pipeline_results"]
        st.success("Cache cleared.")


# ── Main header ───────────────────────────────────────────────────────────────

st.markdown('<p class="main-header">PathwayPulse</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="sub-header">Autonomous Biotech Arbitrage Engine — '
    'detecting cross-indication repurposing signals in real time</p>',
    unsafe_allow_html=True,
)

# ── Run pipeline on button press ─────────────────────────────────────────────

if run_btn and pathway_input.strip():
    pathway = pathway_input.strip()

    with st.spinner(f"Running PathwayPulse for **{pathway}** ..."):
        progress = st.progress(0, text="Ingesting data sources...")

        try:
            ingest_label = "Scraping bioRxiv, medRxiv, Reddit"
            if kol_handles and os.getenv("XAI_API_KEY"):
                ingest_label += f", X/Twitter KOLs ({len(kol_handles)} handles)"
            ingest_label += "..."
            progress.progress(20, text=ingest_label)

            event_dicts, report = cached_pipeline(
                pathway, days_back, include_chemrxiv, kol_handles, model_choice
            )
            progress.progress(80, text="Building Arbitrage Matrix...")

            events = [CrossPollinationEvent(**d) for d in event_dicts]

            # Store in session_state to persist across re-renders
            st.session_state["pipeline_results"] = {
                "pathway": pathway,
                "events": events,
                "report": report,
                "record_count": len(cached_ingest(pathway, days_back, include_chemrxiv, kol_handles)),
            }
            st.session_state["flow_state"] = _build_flow_state(pathway, events)
            progress.progress(100, text="Done.")

        except Exception as e:
            progress.empty()
            st.error(f"Pipeline error: {e}")


# ── Display results ───────────────────────────────────────────────────────────

if "pipeline_results" in st.session_state:
    results = st.session_state["pipeline_results"]
    pathway = results["pathway"]
    events: list[CrossPollinationEvent] = results["events"]
    report: str = results["report"]
    record_count: int = results["record_count"]

    # Metrics row
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.metric("Records Ingested", record_count)
    with col_m2:
        st.metric("Signals Detected", len(events))
    with col_m3:
        high_conf = sum(1 for e in events if e.confidence_score >= 0.5)
        st.metric("High-Confidence", high_conf)
    with col_m4:
        avg_conf = (
            f"{sum(e.confidence_score for e in events) / len(events):.0%}"
            if events else "—"
        )
        st.metric("Avg Confidence", avg_conf)

    st.markdown("---")

    # Two-column layout: graph left, report right
    graph_col, report_col = st.columns([3, 2], gap="large")

    with graph_col:
        st.markdown(f"### Arbitrage Matrix — *{pathway}*")
        if events:
            # Use session_state flow_state to prevent infinite re-renders
            if "flow_state" not in st.session_state:
                st.session_state["flow_state"] = _build_flow_state(pathway, events)

            st.session_state["flow_state"] = streamlit_flow(
                "arbitrage_flow",
                st.session_state["flow_state"],
                layout=TreeLayout(direction="right"),
                fit_view=True,
                height=520,
                allow_new_edges=False,
                animate_new_edges=True,
                enable_node_menu=False,
                enable_edge_menu=False,
                get_node_on_click=False,
                get_edge_on_click=False,
                hide_watermark=True,
            )
        else:
            st.info("No cross-pollination signals detected. Try expanding the date range or using a different pathway.")

    with report_col:
        st.markdown("### Intelligence Report")
        st.markdown(report)

    # Raw events table (expandable)
    if events:
        with st.expander(f"📋 Raw Signal Data ({len(events)} events)", expanded=False):
            for i, ev in enumerate(sorted(events, key=lambda e: e.confidence_score, reverse=True)):
                conf_color = "🔴" if ev.confidence_score >= 0.5 else "⚪"
                st.markdown(
                    f"**{i+1}. {conf_color} {ev.novel_indication}** "
                    f"(confidence: {ev.confidence_score:.0%})"
                )
                st.markdown(f"- Pathway: `{ev.baseline_pathway}`")
                st.markdown(f"- Original indication: {ev.original_indication}")
                st.markdown(f"- Evidence: _{ev.source_evidence[:200]}_")
                if i < len(events) - 1:
                    st.markdown("---")

else:
    # Landing state
    st.markdown("---")
    st.info(
        "👈 Enter a biological pathway in the sidebar and click **Run Analysis** to generate the Arbitrage Matrix.\n\n"
        "**Example pathways to try:**\n"
        "- `IL-6 signaling`\n"
        "- `JAK-STAT pathway`\n"
        "- `PD-1 / PD-L1`\n"
        "- `CRISPR base editing`\n"
        "- `mTOR signaling`"
    )

    st.markdown("### How It Works")
    how_col1, how_col2, how_col3 = st.columns(3)
    with how_col1:
        st.markdown(
            "**1. Ingest**\n\n"
            "Simultaneously pulls from bioRxiv, medRxiv, and Reddit — "
            "up to 600 preprints + community commentary per run."
        )
    with how_col2:
        st.markdown(
            "**2. Synthesize**\n\n"
            "DeepSeek-V3 triages every record in parallel, extracting "
            "cross-indication signals with Pydantic-enforced structured output."
        )
    with how_col3:
        st.markdown(
            "**3. Arbitrage**\n\n"
            "GPT-4o evaluates immunological soundness and renders a "
            "Bear / Bull / Neutral market intelligence report."
        )
