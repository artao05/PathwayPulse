# Codex / Agent Instructions

You are working on the **PathwayPulseV2** branch. Your goal is to continue the integration of Google Science Skills into this codebase according to `IMPLEMENTATION_PLAN.md` and `TASK_LIST.md`.

## CRITICAL RULE: Porting vs. Subprocessing

You will be integrating Google Science Skills into this codebase. 
**DO NOT** invoke the skill CLI scripts via `subprocess.run()`, `os.system()`, or `uv run`. 
The target architecture is **Option B (Python-level wrappers)**, meaning the final deployed app must be fully standalone.

### How to use the Skills:
1. The skills are located locally on this machine at `~/.gemini/config/plugins/science/skills/`.
2. When you need to implement a data source (e.g., OpenTargets), first read its skill documentation:
   `cat ~/.gemini/config/plugins/science/skills/opentargets_database/SKILL.md`
3. Read the Python implementation of the skill to understand the API endpoints and data structures:
   `cat ~/.gemini/config/plugins/science/skills/opentargets_database/scripts/opentargets_api.py`
4. **Port the logic** from the skill script into the PathwayPulse codebase (e.g., creating a new function in `swarm_ingestion.py` or a new `validation_engine.py` module). Use `requests` or `aiohttp` to make the API calls directly.
5. All newly added API calls must handle timeouts and retries gracefully, returning `[]` or `{}` or `None` on failure rather than crashing the pipeline.

## File Organization
- `swarm_ingestion.py`: Functions that gather raw data (PubMed, OpenAlex).
- `ai_orchestrator.py`: LLM reasoning logic. This is where you should add the Validation Engine (OpenTargets) step between the Synthesizer and Executioner.
- `app.py`: The Streamlit dashboard. Update this to surface the new data.

Follow `TASK_LIST.md` to proceed with Phase 2. Good luck!
