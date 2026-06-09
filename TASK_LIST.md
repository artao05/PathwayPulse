# PathwayPulse V2 - Task List

## Phase 1: ClinicalTrials.gov API v2
- [x] Implement `fetch_clinicaltrials_api` using API v2.
- [x] Update `fetch_trial_catalysts` to use API v2.
- [x] Remove BrightData Playwright dependencies for ClinicalTrials.gov.

## Phase 2: Literature & Citation Sources
- [x] Add `fetch_pubmed_literature` to `swarm_ingestion.py`. (Reference: `pubmed-database` skill)
- [x] Integrate OpenAlex citation lookups for preprints. (Reference: `literature-search-openalex` skill)
- [x] Update `ingest_all()` to optionally include PubMed data based on Streamlit UI toggles.
- [x] Add Streamlit UI toggles for PubMed and OpenAlex ingestion.

## Phase 3: Biological Validation Engine
- [x] Add `validate_events` function to `ai_orchestrator.py` that processes `CrossPollinationEvent`s before the Executioner step.
- [x] Implement OpenTargets GraphQL queries in `validate_events` to fetch association scores for `(gene, disease)` pairs. (Reference: `opentargets-database` skill)
- [x] Implement Reactome pathway checks to expand pathway gene lists. (Reference: `reactome-database` skill)
- [x] Add validation scores to the Executioner's system prompt context.

## Phase 4: Pharmacology Enrichment
- [x] Implement ChEMBL queries to fetch drug mechanisms of action and IC50/Ki values. (Reference: `chembl-database` skill)
- [x] Implement openFDA queries to fetch adverse events/safety alerts for identified drugs. (Reference: `openfda-database` skill)
- [x] Pass drug pharmacology summaries to the Executioner for the "Risk Factors" report section.

## Phase 5: Deep Annotations (Stretch)
- [x] Add Ensembl gene ID resolution.
- [x] Add UniProt protein annotation lookups.

## Finalization
- [x] Update Streamlit dashboard to display OpenTargets validation scores and pharmacology data.
- [x] Update `README.md` with final architecture.
