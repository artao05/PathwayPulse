"""
PathwayPulse — Arbitrage Matrix Dashboard
Streamlit app with a dynamic node graph (streamlit-flow) and AI-generated report.
"""
import asyncio
import os

import streamlit as st
from secrets_loader import api_key_status, load_secrets, required_keys_ok

load_secrets()

from streamlit_flow import streamlit_flow
from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
from streamlit_flow.layouts import TreeLayout
from streamlit_flow.state import StreamlitFlowState

from ai_orchestrator import CrossPollinationEvent, DrugPharmacologyProfile, run_pipeline
from swarm_ingestion import fetch_conference_abstracts, fetch_trial_catalysts, ingest_all

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
    include_pubmed: bool,
    include_openalex: bool,
    include_chemrxiv: bool,
    include_clinicaltrials: bool,
    drug: str,
    sponsor: str,
    conference_list: tuple,      # tuple for hashability ("acr", "asco")
    kol_handles: tuple,          # tuple (not list) so @st.cache_data can hash it
    reddit_subs: tuple,          # tuple for hashability
) -> list[dict]:
    return asyncio.run(
        ingest_all(
            pathway_hint=pathway,
            reddit_subreddits=list(reddit_subs),
            twitter_handles=list(kol_handles),
            days_back=days_back,
            include_pubmed=include_pubmed,
            include_openalex=include_openalex,
            include_chemrxiv=include_chemrxiv,
            include_clinicaltrials=include_clinicaltrials,
            drug=drug,
            sponsor=sponsor,
            conference_list=list(conference_list),
        )
    )


@st.cache_data(ttl=3600, show_spinner=False)
def cached_catalysts(
    pathway: str,
    drug: str,
    sponsor: str,
    include_catalysts: bool,
) -> list[dict]:
    """Fetch Catalyst Calendar records via ClinicalTrials.gov API v2."""
    if not include_catalysts:
        return []
    return fetch_trial_catalysts(pathway=pathway, drug=drug, sponsor=sponsor)


def _rank_records_for_analysis(records: list[dict], pathway: str, max_records: int) -> list[dict]:
    """Keep demo runs quick while preserving the most relevant source mix."""
    if max_records <= 0 or len(records) <= max_records:
        return records

    terms = [
        term.lower()
        for term in pathway.replace("-", " ").split()
        if len(term.strip()) >= 3
    ]
    source_bonus = {
        "clinicaltrials": 8,
        "pubmed": 7,
        "acr": 6,
        "asco": 6,
        "medrxiv": 5,
        "biorxiv": 5,
        "chemrxiv": 4,
        "twitter": 3,
        "reddit": 1,
    }

    def score(record: dict) -> tuple[int, int]:
        text = " ".join(
            str(record.get(key, ""))
            for key in ("title", "abstract", "body", "text", "conditions")
        ).lower()
        term_hits = sum(1 for term in terms if term in text)
        return (term_hits * 10 + source_bonus.get(record.get("source", ""), 0), len(text))

    return sorted(records, key=score, reverse=True)[:max_records]


@st.cache_data(ttl=3600, show_spinner=False)
def cached_pipeline(
    pathway: str,
    days_back: int,
    include_pubmed: bool,
    include_openalex: bool,
    include_chemrxiv: bool,
    include_clinicaltrials: bool,
    drug: str,
    sponsor: str,
    include_catalysts: bool,
    conference_list: tuple,
    kol_handles: tuple,
    reddit_subs: tuple,
    model: str,
    include_validation: bool,
    include_pharmacology: bool,
    max_analysis_records: int,
) -> tuple[list[dict], str, list[dict]]:
    records = cached_ingest(
        pathway, days_back, include_pubmed, include_openalex,
        include_chemrxiv, include_clinicaltrials,
        drug, sponsor, conference_list, kol_handles, reddit_subs,
    )
    records = _rank_records_for_analysis(records, pathway, max_analysis_records)
    cats = cached_catalysts(pathway, drug, sponsor, include_catalysts)
    events, report, pharmacology_profiles = asyncio.run(
        run_pipeline(
            records,
            pathway,
            executioner_model=model,
            catalysts=cats or None,
            include_validation=include_validation,
            drug=drug,
            include_pharmacology=include_pharmacology,
        )
    )
    return (
        [e.model_dump() for e in events],
        report,
        [p.model_dump() for p in pharmacology_profiles],
    )


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

    st.markdown("**Drug / Pipeline Filter** (optional)")
    drug_input = st.text_input(
        "Drug or intervention name",
        value="",
        placeholder="e.g. tocilizumab, ruxolitinib, CAR-T",
        help=(
            "Narrows ClinicalTrials.gov searches to a specific drug or intervention. "
            "Leave blank to search by pathway only."
        ),
    )
    drug = drug_input.strip()

    sponsor_input = st.text_input(
        "Sponsor / company name",
        value="",
        placeholder="e.g. Roche, Pfizer, AbbVie",
        help="Optionally filter ClinicalTrials.gov results to a specific lead sponsor.",
    )
    sponsor = sponsor_input.strip()

    st.markdown("**Data Sources**")
    _key_status = api_key_status()
    with st.expander("API key status", expanded=not required_keys_ok()):
        st.caption("Required for Run Analysis")
        st.write(f"{'✅' if _key_status['OPENAI_API_KEY'] else '❌'} OPENAI_API_KEY")
        st.write(f"{'✅' if _key_status['AIMLAPI_KEY'] else '❌'} AIMLAPI_KEY")
        st.caption("Optional")
        st.write(f"{'✅' if _key_status['NCBI_API_KEY'] else '—'} NCBI_API_KEY (PubMed rate limit)")
        st.write(f"{'✅' if _key_status['USER_EMAIL'] else '—'} USER_EMAIL (NCBI/OpenAlex polite pool)")
        st.write(f"{'✅' if _key_status['OPENALEX_API_KEY'] else '—'} OPENALEX_API_KEY (citations)")
        st.write(f"{'✅' if _key_status['XAI_API_KEY'] else '—'} XAI_API_KEY (Twitter/KOL)")
        st.write(
            f"{'✅' if _key_status['BRIGHTDATA_BROWSER_AUTH'] else '—'} "
            "BRIGHTDATA_BROWSER_AUTH (ACR abstracts)"
        )
        if not required_keys_ok():
            st.warning(
                "Add missing keys in **Manage app → Settings → Secrets** using TOML format. "
                "See `.streamlit/secrets.toml.example` in the repo."
            )

    days_back = st.slider("Days of source history", min_value=1, max_value=14, value=3)
    run_depth = st.selectbox(
        "Run depth",
        options=["Demo (fast)", "Standard", "Full"],
        index=0,
        help=(
            "Demo mode analyzes the most relevant 80 records. Standard analyzes "
            "180. Full analyzes everything ingested and can take several minutes."
        ),
    )
    _max_analysis_records = {
        "Demo (fast)": 80,
        "Standard": 180,
        "Full": 0,
    }[run_depth]
    include_pubmed = st.checkbox(
        "Include PubMed (peer-reviewed)",
        value=True,
        help=(
            "Fetches recent peer-reviewed abstracts for the pathway via "
            "NCBI E-utilities. No API key required; NCBI_API_KEY is optional."
        ),
    )
    include_openalex = st.checkbox(
        "Enrich preprints with OpenAlex citations",
        value=True,
        help=(
            "Adds citation counts and journal-location metadata to DOI-bearing "
            "bioRxiv / medRxiv / ChemRxiv records. OPENALEX_API_KEY is optional."
        ),
    )
    include_validation = st.checkbox(
        "Run biological validation",
        value=True,
        help=(
            "Uses OpenTargets and Reactome to resolve target/disease context "
            "and add grounding scores before report generation."
        ),
    )
    include_pharmacology = st.checkbox(
        "Run pharmacology enrichment",
        value=True,
        help=(
            "Uses ChEMBL and openFDA to add mechanism, IC50/Ki, label, "
            "and adverse-event context for detected drugs."
        ),
    )
    include_chemrxiv = st.checkbox("Include ChemRxiv (preclinical)", value=False)

    _has_brightdata = bool(os.getenv("BRIGHTDATA_BROWSER_AUTH"))
    include_clinicaltrials = st.checkbox(
        "Include ClinicalTrials.gov text records",
        value=True,
        help=(
            "Fetches active/recruiting trials matching your pathway via "
            "the free ClinicalTrials.gov API v2. No API key required."
        ),
    )

    include_catalysts = st.checkbox(
        "Show Catalyst Calendar",
        value=True,
        help=(
            "Surfaces upcoming / overdue trial readouts with start date, expected "
            "primary-completion date, and days-until-readout. "
            "Uses the free ClinicalTrials.gov API v2 — no API key required."
        ),
    )

    _conf_options = {
        "acr":  "ACR (Rheumatology)",
        "asco": "ASCO (Oncology) — NGO risk",
    }
    if _has_brightdata:
        _conf_selected = st.multiselect(
            "Conference abstracts (BrightData)",
            options=list(_conf_options.keys()),
            default=[],
            format_func=lambda k: _conf_options[k],
            help=(
                "Optional slow source. Scrape meeting abstracts — the earliest "
                "public disclosure of clinical trial data, months before bioRxiv. "
                "ACR is green-tier (open robots.txt). "
                "ASCO carries NGO-classification risk and returns [] if blocked "
                "(requires BrightData KYC to unlock)."
            ),
        )
    else:
        st.caption(
            "Optional: add BRIGHTDATA_BROWSER_AUTH in Secrets to enable ACR conference abstracts."
        )
        _conf_selected = []

    conference_list: tuple = tuple(_conf_selected)

    st.markdown("**Reddit Subreddits**")

    # Load default subreddits from reddit_subreddits.json if present
    import json as _json, pathlib as _pathlib
    _default_subs: list[str] = ["biotech", "investing", "stocks"]
    try:
        _subs_path = _pathlib.Path(__file__).parent / "reddit_subreddits.json"
        if _subs_path.exists():
            _default_subs = _json.loads(_subs_path.read_text()).get("subreddits", _default_subs)
    except Exception:
        pass

    subs_input = st.text_area(
        "One subreddit per line or comma-separated",
        value="\n".join(_default_subs),
        placeholder="biotech\ninvesting\nstocks",
        height=90,
        help="Strip the r/ prefix — just the bare name. Monitored via Reddit RSS feed.",
    )
    reddit_subs: tuple = tuple(
        s.strip().lstrip("r/").lstrip("/")
        for s in subs_input.replace(",", "\n").splitlines()
        if s.strip()
    )

    st.markdown("**X / Twitter KOL Handles** (optional)")

    # Load default handles from kol_handles.json if present
    _default_handles: list[str] = []
    try:
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
        cached_catalysts.clear()
        for key in ("flow_state", "pipeline_results"):
            if key in st.session_state:
                del st.session_state[key]
        st.success("Cache cleared.")


# ── Main header ───────────────────────────────────────────────────────────────

st.markdown('<p class="main-header">PathwayPulse</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="sub-header">Autonomous Biotech Arbitrage Engine — '
    'detecting cross-indication repurposing signals in real time</p>',
    unsafe_allow_html=True,
)

if not required_keys_ok():
    st.error(
        "Missing API keys. Add `OPENAI_API_KEY` and `AIMLAPI_KEY` in "
        "**Manage app → Settings → Secrets** (Streamlit Cloud) or `.env` (local). "
        "Use TOML format with quotes — see `.streamlit/secrets.toml.example`."
    )
elif "pipeline_results" not in st.session_state:
    st.info(
        "Click **Run Analysis** in the sidebar to generate the Arbitrage Matrix. "
        "First run takes ~2–4 minutes; results are cached for 1 hour."
    )

# ── Run pipeline on button press ─────────────────────────────────────────────

if run_btn and pathway_input.strip():
    pathway = pathway_input.strip()

    with st.spinner(f"Running PathwayPulse for **{pathway}** ..."):
        progress = st.progress(0, text="Ingesting data sources...")

        try:
            sub_names = ", ".join(f"r/{s}" for s in reddit_subs[:3])
            if len(reddit_subs) > 3:
                sub_names += f" +{len(reddit_subs) - 3} more"
            ingest_label = f"Scraping bioRxiv, medRxiv, Reddit ({sub_names})"
            if include_pubmed:
                ingest_label += ", PubMed"
            if include_openalex:
                ingest_label += ", OpenAlex citations"
            if include_validation:
                ingest_label += ", OpenTargets/Reactome validation"
            if include_pharmacology:
                ingest_label += ", ChEMBL/openFDA pharmacology"
            if _max_analysis_records:
                ingest_label += f", {run_depth.lower()} cap ({_max_analysis_records} records)"
            if include_clinicaltrials:
                ingest_label += ", ClinicalTrials.gov (API v2)"
            if conference_list:
                conf_names = ", ".join(c.upper() for c in conference_list)
                ingest_label += f", {conf_names} abstracts"
            if kol_handles and os.getenv("XAI_API_KEY"):
                ingest_label += f", X/Twitter KOLs ({len(kol_handles)} handles)"
            ingest_label += "..."
            progress.progress(20, text=ingest_label)

            event_dicts, report, profile_dicts = cached_pipeline(
                pathway, days_back, include_pubmed, include_openalex,
                include_chemrxiv, include_clinicaltrials,
                drug, sponsor, include_catalysts, conference_list, kol_handles,
                reddit_subs, model_choice, include_validation, include_pharmacology,
                _max_analysis_records,
            )
            progress.progress(70, text="Building Arbitrage Matrix...")

            events = [CrossPollinationEvent(**d) for d in event_dicts]
            pharmacology_profiles = [
                DrugPharmacologyProfile(**d) for d in profile_dicts
            ]

            _records = cached_ingest(
                pathway, days_back, include_pubmed, include_openalex,
                include_chemrxiv, include_clinicaltrials,
                drug, sponsor, conference_list, kol_handles, reddit_subs,
            )
            _analyzed_records = _rank_records_for_analysis(
                _records,
                pathway,
                _max_analysis_records,
            )
            _catalysts = cached_catalysts(pathway, drug, sponsor, include_catalysts)

            # Store in session_state to persist across re-renders
            st.session_state["pipeline_results"] = {
                "pathway": pathway,
                "events": events,
                "report": report,
                "record_count": len(_records),
                "analysis_record_count": len(_analyzed_records),
                "records": _records,
                "catalysts": _catalysts,
                "pharmacology_profiles": pharmacology_profiles,
                "drug": drug,
                "sponsor": sponsor,
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
    analysis_record_count: int = results.get("analysis_record_count", record_count)
    raw_records: list[dict] = results.get("records", [])
    catalysts: list[dict] = results.get("catalysts", [])
    pharmacology_profiles: list[DrugPharmacologyProfile] = [
        p if isinstance(p, DrugPharmacologyProfile) else DrugPharmacologyProfile(**p)
        for p in results.get("pharmacology_profiles", [])
    ]

    metric_cols = st.columns(8 if catalysts else 7)

    with metric_cols[0]:
        st.metric("Records Ingested", record_count)
    with metric_cols[1]:
        st.metric("Records Analyzed", analysis_record_count)
    with metric_cols[2]:
        st.metric("Signals Detected", len(events))
    with metric_cols[3]:
        high_conf = sum(1 for e in events if e.confidence_score >= 0.5)
        st.metric("High-Confidence", high_conf)
    with metric_cols[4]:
        avg_conf = (
            f"{sum(e.confidence_score for e in events) / len(events):.0%}"
            if events else "—"
        )
        st.metric("Avg Confidence", avg_conf)
    validation_supported = sum(
        1 for e in events
        if e.opentargets_association_score is not None
        and e.opentargets_association_score > 0
    )
    if catalysts:
        with metric_cols[5]:
            actionable = [c for c in catalysts if c["bucket"] in ("overdue", "imminent")]
            near_cat = next(
                (c for c in catalysts if c["days_until_readout"] is not None
                 and c["days_until_readout"] >= 0 and not c["results_posted"]),
                None,
            )
            if near_cat and near_cat["days_until_readout"] is not None:
                st.metric("Next Readout", f"{near_cat['days_until_readout']}d",
                          delta=f"{len(actionable)} imminent" if actionable else None,
                          delta_color="inverse")
            else:
                st.metric("Trials Tracked", len(catalysts))
        with metric_cols[6]:
            st.metric("OT Supported", validation_supported)
        with metric_cols[7]:
            st.metric("Drug Profiles", len(pharmacology_profiles))
    else:
        with metric_cols[5]:
            st.metric("OT Supported", validation_supported)
        with metric_cols[6]:
            st.metric("Drug Profiles", len(pharmacology_profiles))

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
                # Source link — prefer title + URL, fall back gracefully
                display_label = ev.source_title or ev.source_label or ev.source_type or "source"
                if ev.source_url:
                    st.markdown(f"- Source: [{display_label}]({ev.source_url})")
                else:
                    badge = ev.source_label or ev.source_type or "unknown"
                    st.markdown(f"- Source: `{badge}`")
                if ev.citation_count is not None:
                    st.markdown(f"- OpenAlex citations: {ev.citation_count}")
                if ev.published_version_source:
                    if ev.published_version_url:
                        st.markdown(
                            f"- Published version: [{ev.published_version_source}]"
                            f"({ev.published_version_url})"
                        )
                    else:
                        st.markdown(f"- Published version: {ev.published_version_source}")
                if ev.validation_status != "not_run":
                    st.markdown(f"- Validation status: `{ev.validation_status}`")
                if ev.opentargets_association_score is not None:
                    score = ev.opentargets_association_score
                    target_label = ev.opentargets_target_symbol or ev.opentargets_target_id
                    disease_label = ev.opentargets_disease_name or ev.opentargets_disease_id
                    st.markdown(
                        f"- OpenTargets: `{target_label}` ↔ `{disease_label}` "
                        f"score `{score:.3f}`"
                    )
                if ev.reactome_pathway_match:
                    fdr_label = (
                        f" (FDR {ev.reactome_pathway_fdr:.2g})"
                        if ev.reactome_pathway_fdr is not None else ""
                    )
                    st.markdown(f"- Reactome: {ev.reactome_pathway_match}{fdr_label}")
                if ev.ensembl_gene_annotations:
                    gene_labels = ", ".join(
                        f"{row.get('symbol') or row.get('query')} ({row.get('ensembl_gene_id')})"
                        for row in ev.ensembl_gene_annotations[:3]
                        if row.get("ensembl_gene_id")
                    )
                    if gene_labels:
                        st.markdown(f"- Ensembl: {gene_labels}")
                if ev.uniprot_annotations:
                    protein_labels = ", ".join(
                        f"{row.get('protein_name') or row.get('entry_name')} ({row.get('accession')})"
                        for row in ev.uniprot_annotations[:2]
                        if row.get("accession")
                    )
                    if protein_labels:
                        st.markdown(f"- UniProt: {protein_labels}")
                if ev.validation_notes:
                    st.markdown(f"- Validation notes: {'; '.join(ev.validation_notes[:2])}")
                st.markdown(f"- Evidence: _{ev.source_evidence[:250]}_")
                if i < len(events) - 1:
                    st.markdown("---")

    if events and any(ev.validation_status != "not_run" for ev in events):
        with st.expander("🧬 Biological Validation", expanded=False):
            for ev in sorted(events, key=lambda e: e.confidence_score, reverse=True)[:12]:
                target_label = ev.opentargets_target_symbol or ev.opentargets_target_id or "unresolved target"
                disease_label = ev.opentargets_disease_name or ev.novel_indication
                score_label = (
                    f"{ev.opentargets_association_score:.3f}"
                    if ev.opentargets_association_score is not None else "unresolved"
                )
                st.markdown(f"**{ev.novel_indication}**")
                st.caption(
                    f"OpenTargets: {target_label} -> {disease_label} | score {score_label}"
                )
                if ev.reactome_pathway_match:
                    fdr_label = (
                        f" | FDR {ev.reactome_pathway_fdr:.2g}"
                        if ev.reactome_pathway_fdr is not None else ""
                    )
                    st.caption(f"Reactome: {ev.reactome_pathway_match}{fdr_label}")
                if ev.opentargets_top_disease_targets:
                    top_targets = ", ".join(
                        f"{row.get('target_symbol', '')} ({row.get('score', 0):.2f})"
                        for row in ev.opentargets_top_disease_targets[:3]
                        if row.get("target_symbol")
                    )
                    if top_targets:
                        st.caption(f"Top disease targets: {top_targets}")
                if ev.ensembl_gene_annotations:
                    gene_labels = ", ".join(
                        f"{row.get('symbol') or row.get('query')} {row.get('ensembl_gene_id')}"
                        for row in ev.ensembl_gene_annotations[:3]
                        if row.get("ensembl_gene_id")
                    )
                    if gene_labels:
                        st.caption(f"Ensembl: {gene_labels}")
                if ev.uniprot_annotations:
                    protein_labels = ", ".join(
                        f"{row.get('accession')} {row.get('protein_name') or row.get('entry_name')}"
                        for row in ev.uniprot_annotations[:2]
                        if row.get("accession")
                    )
                    if protein_labels:
                        st.caption(f"UniProt: {protein_labels}")

    if pharmacology_profiles:
        with st.expander(f"💊 Pharmacology & Safety ({len(pharmacology_profiles)} drugs)", expanded=False):
            for profile in pharmacology_profiles:
                st.markdown(f"**{profile.drug_name}**")
                meta_parts = []
                if profile.chembl_pref_name:
                    meta_parts.append(profile.chembl_pref_name)
                if profile.chembl_molecule_id:
                    meta_parts.append(profile.chembl_molecule_id)
                if profile.molecule_type:
                    meta_parts.append(profile.molecule_type)
                if profile.max_phase is not None:
                    meta_parts.append(f"max phase {profile.max_phase:g}")
                if profile.first_approval:
                    meta_parts.append(f"first approval {profile.first_approval}")
                if profile.black_box_warning is not None:
                    meta_parts.append(
                        "boxed warning flagged" if profile.black_box_warning else "no boxed warning flag"
                    )
                if meta_parts:
                    st.caption(" · ".join(meta_parts))
                if profile.mechanisms:
                    st.markdown("Mechanism")
                    for mech in profile.mechanisms[:3]:
                        action = mech.get("action_type") or "MOA"
                        moa = mech.get("mechanism_of_action") or "mechanism not specified"
                        target = mech.get("target_name") or mech.get("target_chembl_id") or "target not specified"
                        st.caption(f"{action}: {moa} ({target})")
                if profile.bioactivities:
                    st.markdown("Representative IC50/Ki")
                    for act in profile.bioactivities[:4]:
                        value = act.get("standard_value")
                        units = act.get("standard_units") or ""
                        nm = act.get("normalized_value_nM")
                        nm_label = f", {nm:.2g} nM" if nm is not None else ""
                        target = act.get("target_pref_name") or act.get("target_chembl_id") or "target not specified"
                        st.caption(
                            f"{act.get('standard_type', '')} {act.get('standard_relation', '')} "
                            f"{value} {units}{nm_label} at {target}".strip()
                        )
                if profile.openfda_total_events is not None:
                    serious = (
                        f"; {profile.openfda_serious_events:,} serious"
                        if profile.openfda_serious_events is not None else ""
                    )
                    st.caption(f"openFDA FAERS: {profile.openfda_total_events:,} reports{serious}")
                if profile.openfda_top_reactions:
                    reactions = ", ".join(
                        f"{row.get('reaction')} ({row.get('count')})"
                        for row in profile.openfda_top_reactions[:5]
                        if row.get("reaction")
                    )
                    if reactions:
                        st.caption(f"Top reactions: {reactions}")
                for warning in profile.openfda_label_warnings[:2]:
                    st.caption(f"Label warning: {warning}")
                if profile.notes:
                    st.caption("Notes: " + "; ".join(profile.notes[:2]))

    # ── Catalyst Calendar ──────────────────────────────────────────────────────
    if catalysts:
        _BUCKET_ICON = {
            "overdue": "🔴",
            "imminent": "🟠",
            "near": "🟡",
            "upcoming": "🔵",
            "reported": "✅",
        }
        _BUCKET_LABEL = {
            "overdue":  "Overdue — results expected, none posted",
            "imminent": "Imminent — readout within 90 days",
            "near":     "Near-term — readout 91–180 days out",
            "upcoming": "Upcoming — readout > 180 days or TBD",
            "reported": "Reported — results already posted",
        }

        with st.expander(
            f"📅 Catalyst Calendar — {len(catalysts)} trials tracked",
            expanded=True,
        ):
            # Group by bucket in priority order
            bucket_order = ["overdue", "imminent", "near", "upcoming", "reported"]
            grouped_cats: dict[str, list[dict]] = {b: [] for b in bucket_order}
            for cat in catalysts:
                grouped_cats.setdefault(cat["bucket"], []).append(cat)

            for bucket in bucket_order:
                bucket_cats = grouped_cats.get(bucket, [])
                if not bucket_cats:
                    continue

                icon = _BUCKET_ICON.get(bucket, "•")
                label = _BUCKET_LABEL.get(bucket, bucket.title())
                st.markdown(f"**{icon} {label}** ({len(bucket_cats)})")

                for cat in bucket_cats:
                    nct_id = cat.get("nct_id", "")
                    title  = cat.get("title", nct_id)
                    url    = cat.get("url", f"https://clinicaltrials.gov/study/{nct_id}")
                    phase  = cat.get("phase", "")
                    status = cat.get("status", "")
                    sponsor_name = cat.get("lead_sponsor", "")
                    interventions = cat.get("interventions", [])
                    conditions = cat.get("conditions", [])
                    pc_date = cat.get("primary_completion_date", "")
                    pc_type = cat.get("primary_completion_type", "")
                    start   = cat.get("start_date", "")
                    window  = cat.get("readout_window", "TBD")
                    days    = cat.get("days_until_readout")

                    # Days-until badge
                    if days is None:
                        days_badge = "TBD"
                    elif days < 0:
                        days_badge = f"{abs(days)}d overdue"
                    else:
                        days_badge = f"{days}d"

                    # Build compact one-liner
                    parts = []
                    if phase:
                        parts.append(phase)
                    if status:
                        parts.append(status)
                    if sponsor_name:
                        parts.append(f"*{sponsor_name}*")
                    meta = " · ".join(parts)

                    pc_label = f"{pc_date}"
                    if pc_type == "ESTIMATED":
                        pc_label += " (est.)"

                    drug_str = ", ".join(interventions[:3]) if interventions else ""
                    cond_str = ", ".join(conditions[:2]) if conditions else ""

                    col_title, col_readout, col_badge = st.columns([5, 2, 1])
                    with col_title:
                        st.markdown(f"[{title[:90]}]({url})")
                        detail_parts = []
                        if meta:
                            detail_parts.append(meta)
                        if drug_str:
                            detail_parts.append(f"Drug: {drug_str}")
                        if cond_str:
                            detail_parts.append(f"Conditions: {cond_str}")
                        if start:
                            detail_parts.append(f"Started: {start}")
                        st.caption(" · ".join(detail_parts))
                    with col_readout:
                        st.caption(f"Readout: {pc_label}" if pc_date else f"Window: {window}")
                    with col_badge:
                        st.caption(days_badge)

                st.markdown("")

    # Ingested Sources expander — all raw records with links grouped by source type
    if raw_records:
        from collections import defaultdict
        grouped: dict = defaultdict(list)
        for rec in raw_records:
            grouped[rec.get("source", "unknown")].append(rec)

        source_order = [
            "biorxiv", "medrxiv", "pubmed", "chemrxiv", "clinicaltrials",
            "acr", "asco", "reddit", "twitter",
        ]
        ordered_keys = [k for k in source_order if k in grouped] + [
            k for k in grouped if k not in source_order
        ]

        with st.expander(f"🗂 Ingested Sources ({len(raw_records)} records)", expanded=False):
            for src_key in ordered_keys:
                recs = grouped[src_key]
                label_map = {
                    "biorxiv": "bioRxiv", "medrxiv": "medRxiv",
                    "pubmed": "PubMed", "chemrxiv": "ChemRxiv",
                    "clinicaltrials": "ClinicalTrials.gov",
                    "acr": "ACR Abstracts", "asco": "ASCO Abstracts",
                    "reddit": "Reddit", "twitter": "X / Twitter",
                }
                src_display = label_map.get(src_key, src_key.title())
                st.markdown(f"**{src_display}** — {len(recs)} records")
                for rec in recs[:20]:
                    title = rec.get("title") or rec.get("body", "")[:60]
                    url = rec.get("url", "")
                    label = rec.get("source_label", src_display)
                    if url:
                        st.markdown(f"  - [{title[:80]}]({url})")
                    else:
                        st.markdown(f"  - {title[:80]}")
                    meta_bits = []
                    citation_count = rec.get("citation_count")
                    if citation_count is not None:
                        meta_bits.append(f"{citation_count} OpenAlex citations")
                    published_source = rec.get("published_version_source")
                    if published_source:
                        meta_bits.append(f"published version: {published_source}")
                    if rec.get("journal"):
                        meta_bits.append(str(rec["journal"])[:80])
                    if meta_bits:
                        st.caption(" · ".join(meta_bits))
                if len(recs) > 20:
                    st.caption(f"  … and {len(recs) - 20} more")

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
            "Simultaneously pulls from bioRxiv, medRxiv, PubMed, Reddit, "
            "and optional clinical / conference sources."
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
