# Changelog

## Unreleased - 2026-11-15

### Azure deployment (live)
- Deployed to a Udacity Vocareum lab subscription (westus) with the new RG-scoped `infra/lab/main.bicep`: Foundry + project + gpt-4o-mini, AI Search (Free, 1,034 docs), Storage, Key Vault, ACR (`az acr build`), Container Apps (Streamlit + FastAPI) and App Insights. Nothing was blocked by policy.
- `infra/resources.bicep`: new `openAiSku` param (default DataZoneStandard, because GlobalStandard returns `ServiceModelDeprecating` and Standard returns `ServiceModelDeprecated` for gpt-4o-mini 2024-07-18), plus `searchSku`, `deployApps` (two-pass so Key Vault secrets exist before the apps), `deployApi` (FastAPI as a second Container App), `deployOpenAi` (OpenAI-compatible fallback) and `purgeProtection`. The model deployment now waits for the project to avoid `RequestConflict`.
- **Red-team rule-1 false positives (fix).** Live Azure runs 6624778b and 072c6c63 (the API's short default request) ended `not_finalized` on `red_team_pass`. Reproduced locally (7a7c4ba8, 8578806a): the reviewer filed rule 1 ("invented clinical facts") on cited restatements of NCD 280.14 coverage criteria and on a framing sentence that only repeated the case facts, and code confirmation for rule 1 only knew about absence statements. `confirm_red_team` now drops a rule-1 issue only when code shows (a) a cited sentence with criteria wording whose numbers and at least 60% of content words are in the cited excerpt, or (b) an uncited, number-free sentence whose content words are all in the published case facts or generic appeal wording (the intake's missing_information does not count). The verifier passes the CASE FACTS to the MCP tool (`case_json`, optional). Invented patient facts, including ones that borrow policy wording or a policy citation, are still confirmed (`test_red_team_rule1_policy_restatement_and_case_framing_regression`). Gate mutation eval 48/48 (8 drafts, now including the Azure-run log), injection 16/16 with 0 false positives on 2,652 real requests.
- Live verification: 12/12 checks, 26.9 s, $0.0033 on the Azure API. Two runs with the short default request failed `red_team_pass`; both are reported in docs/AZURE_DEPLOY.md.

## 0.1.0 - 2026-11-15

First release for the Project 7 capstone and the Project 8 defense.

### Core
- **Data.** Public-data snapshot of CA DMHC IMR (42,710), NY DFS external appeals (62,249) and CMS NCD (345 current, 1,034 chunks), with a cleaning log and sha256 manifest. LCD is optional and local only.
- **Retrieval.** Hybrid policy retrieval: vectorised BM25 plus LSA/FAISS, RRF k=60, a LangChain BaseRetriever, and an Azure AI Search adapter with an index loader.
- **Models and statistics.**
  - P3: time-split overturn model (HistGB vs LR, sigmoid calibration, baselines).
  - P4: request-sentence TF-IDF + LR model with a Findings leakage bound.
  - P2: statistical tests with effect sizes and Bonferroni correction.
- **Agents.** LangGraph agents: input guard → intake → planner → orchestrator ↔ policy retriever (ReAct), criteria matcher, risk analyst (MCP), appeal writer, verifier → gate.
- **MCP server.** 14 tools, 8 resources and 3 prompts over stdio and streamable HTTP with bearer auth and a server policy engine.
- **Checks and receipts.** 12 required checks (PASS / FAIL / NOT_RUN; NOT_RUN blocks the run), and an HMAC receipt with git sha, contract sha and feed versions. Human sign-off re-signs the receipt.

### Apps and operations
- **Interfaces.** Streamlit app (8 tabs, human sign-off), FastAPI, the CLI `python -m claimguard`, a Dockerfile and docker compose.
- **Observability.** OpenTelemetry to App Insights or OTLP; monitoring of run health and PSI drift; a gardener that proposes fixes only.
- **Azure.** Bicep and azd: Foundry resource and project, gpt-4o-mini deployment, AI Search, Storage, Key Vault, ACR, Container Apps and App Insights. It is validated offline and not deployed.
- **CI and tests.** 71 offline tests, ruff and mypy clean, a secret scan, and `ci/ci.yml` for the user to add.

### Fixes found by the live runs and the evaluation (all logs kept)
- **Red-team false positives (eb15f66).** In runs ee03fc07 and ce068f7d, the red-team LLM flagged supported, verbatim-quoted sentences (rule 2) and statements that a fact was missing (rule 1). Both runs ended `not_finalized`. Commit 3f04269 changed rule 2 so that code confirms citation support (unknown id, inline quote not verbatim, or under 15% content-word overlap) and rule 1 so that it ignores absence statements. Writer rule 8 now sends missing facts to the reviewer questions. The same cases then finalized (692679ba, 509c6111).
- **Number grounding.** The mutation test showed that an invented 93.7% passed because a source value of 94 was within the old 0.5% tolerance. Grounding is now rounding-aware.
- **Injection scanner.** The first eval blocked 12 of 16 prompts. Patterns were added for the DAN persona, fabricated records, invented citations and filing on someone's behalf. There were 0 false positives on 2,652 real requests.
- **Data and baseline.** The NCD export had mixed latin-1/UTF-8 text, now repaired. The majority-class baseline now uses train + validation.
