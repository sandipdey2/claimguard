# Changelog

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
