"""Generate docs/COVERAGE.md: ClaimGuard vs the course diagrams (knowledge graph 34 nodes, AI Agent build 37 items,
LangGraph + MCP 17 components). Statuses: full | partial | missing | out of scope. Counts are computed, never typed."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

KG = {
    "Foundations": [
        ("LLM reasoning", "full", "claimguard/agents.py::build_graph", "gpt-4o-mini (temperature 0) in 6 LLM roles: intake, planner, policy retriever (ReAct), criteria matcher, appeal writer, red team.", "eval/logs/live_*.json (8-10 LLM calls / run)"),
        ("Prompt patterns", "full", "agents.py::SYSTEM, prompts.py, MCP prompts", "role system prompts, ReAct 'Thought:' lines, MCP prompt templates (appeal_letter, red_team_review, garden_review), structured output.", "verify_mcp.py prompts/get"),
        ("Tool use / function calling", "full", "agents.py::policy_retriever (bind_tools)", "LangChain bind_tools over MCP tools loaded with langchain-mcp-adapters; deterministic MCP calls for risk tools.", "spans mcp.tools/call.* in live logs; test_agents_e2e"),
        ("Embeddings & vectors", "full", "retrieval.py::HybridIndex", "TF-IDF -> SVD 256-d LSA vectors in FAISS IndexFlatIP + BM25, RRF fusion; same vectors pushed to Azure AI Search. Limit: LSA, not neural embeddings.", "eval/summary.json retrieval: dense recall@1 0.945"),
        ("Context windows", "partial", "contract.json budget, tool_arg_limits", "token budget per run (60k), query length and k limits, per-call token usage in spans. Limit: no per-slot context inspector.", "cost.total_tokens in every receipt"),
    ],
    "Retrieval & Memory": [
        ("Classical RAG", "full", "agents.py::risk_analyst, retrieval.py::PolicyRetriever", "fixed retrieval before the writer (precedents, cohort) + a LangChain BaseRetriever; deterministic policy search fallback when the ReAct agent does not search.", "test_retrieval.py; decision 'retrieval_fallback'"),
        ("Graph RAG", "partial", "tools.py::graph_neighbors, resource graph://coverage-graph", "treatment subcategory -> diagnosis categories -> NCD documents graph. Limit: one hop, served over MCP but not used by the agents in v0.1.", "test_tools.py::test_score_and_graph"),
        ("Agentic RAG", "full", "agents.py::policy_retriever", "the LLM chooses queries and calls search_coverage_policy / get_ncd (up to 3 rounds), then selects excerpt ids it may cite.", "live logs policy_selected + spans"),
        ("Short-term memory", "full", "agents.py::CaseState", "typed LangGraph state carries intake, plan, evidence, draft, checks and trace across nodes.", "test_agents_e2e.py"),
        ("Long-term memory", "missing", "-", "by design: no patient memory across runs (no PHI retention). Receipts are stored, not recalled.", "-"),
        ("Episodic memory", "partial", "monitoring.py::load_runs, scripts/garden.py", "past run logs are mined for recurring failures. Limit: not recalled into the agents' prompts.", "eval/garden_report.json"),
    ],
    "Agent patterns": [
        ("ReAct loop", "full", "agents.py::policy_retriever", "Thought -> tool call -> observation, max 3 rounds from the contract.", "live trace type react"),
        ("Planner -> executor", "full", "agents.py::planner, orchestrator", "LLM plan; code-enforced orchestrator executes eligible steps in plan order.", "route in every live log"),
        ("Multi-agent orchestration", "full", "agents.py::build_graph", "LangGraph supervisor + 5 specialists + gate.", "test_agents_e2e exact route"),
        ("Context graph traversal", "partial", "tools.py::graph_neighbors", "one-hop neighbours with overturn rates. Limit: no multi-hop path ranking.", "verify_mcp.py graph resource"),
        ("Tool selection & routing", "full", "contract.json agents.*.tools, server_policy.py", "per-agent allow-lists; the MCP server re-validates k, query length and outcome access.", "verify_mcp.py refusals (2 per transport)"),
        ("Reflection / self-critique", "full", "agents.py::appeal_writer pre-check, verifier", "writer pre-check -> one revision; red team (LLM proposes, code confirms).", "test_agents_e2e invent_number fixed by revision"),
    ],
    "Production & governance": [
        ("Confidence scoring", "partial", "models.py (calibrated), OverturnModel.band", "calibrated overturn signal with band vs base rate. Limit: no confidence score for the draft itself; the gate is binary.", "eval/model_report.json calibration"),
        ("Policy gates", "full", "guard.py, harness.py::verify, release_decision", "input guard, 12 required checks, NOT_RUN blocks, human sign-off release check.", "test_harness.py; eval gate mutation 40/40"),
        ("Audit trail design", "full", "harness.py::sign_receipt, human_signoff", "HMAC-SHA256 receipt with git sha, contract sha, feed sha, input/draft/trace hashes; sign-off re-signs with previous_signature.", "test_harness tamper test"),
        ("Decision reasoning logs", "full", "harness.py::RunContext.decide", "orchestrator routes, budget stops and fallbacks logged with rationale.", "ctx.decisions in run state"),
        ("Eval & observability", "full", "scripts/run_eval.py, observability.py, app Monitoring tab", "offline eval, OpenTelemetry spans to App Insights / OTLP, run health + PSI drift.", "eval/summary.json"),
        ("Cost / token economics", "full", "harness.py::price, cost_summary", "per-call list-price cost; budget $0.02 per run in the contract.", "$0.0033-0.0050 per live run"),
    ],
    "RAG modes & agentic search": [
        ("Agentic search: file search", "missing", "-", "not in v0.1 (corpus is structured policy text, searched via MCP).", "-"),
        ("Skill-loading tool", "missing", "-", "not in v0.1.", "-"),
        ("Database tools", "partial", "tools.py::cohort_stats, hypothesis_tests, get_imr_case", "parameterised read-only queries over the IMR / DFS tables. Limit: no free-form SQL tool.", "verify_mcp.py"),
        ("Web search (allowlisted)", "out of scope", "-", "by design: offline, checksummed public snapshot; Azure AI Search is the online retrieval option.", "-"),
        ("Memory tool", "missing", "-", "no memory by design (see long-term memory).", "-"),
        ("Shell tool (sandboxed)", "out of scope", "-", "not needed for this product; no code execution.", "-"),
        ("Context-window inspector", "partial", "app.py Monitoring tab (spans)", "per-call input/output tokens per agent from spans. Limit: no per-slot breakdown.", "spans in live logs"),
    ],
    "Frontier": [
        ("Memory & learning loops", "partial", "scripts/garden.py", "recurring failures -> proposals (propose-only; humans apply). Example: red-team false positives -> code confirmation in 3f04269.", "eval/garden_report.json, CHANGELOG"),
        ("Self-improving agents", "partial", "agents.py revision loop + gardener", "one bounded revision per run; no autonomous prompt/code edits.", "test_agents_e2e"),
        ("Multi-modal reasoning", "missing", "-", "text only; PDF/scan denial letters are not parsed in v0.1.", "-"),
        ("Agentic workflows at scale", "partial", "api/main.py (async), infra Container Apps scale rule", "async FastAPI, Container Apps 0-3 replicas on HTTP concurrency. Limit: no job queue; not load-tested.", "infra/resources.bicep"),
    ],
}

BUILD = [
    ("1 Purpose", "Problem / goal", "full", "README", "cited appeal drafts + denial-risk briefs for denied claims."),
    ("1 Purpose", "Target users", "full", "README, docs/GUMROAD_LISTING.md", "patients and authorised representatives, patient advocates, provider billing / appeals teams."),
    ("1 Purpose", "Scope & non-goals", "full", "guard.py REFUSE, disclaimer", "not legal/medical advice; never files; refuses invented patients, impersonation, guarantees."),
    ("1 Purpose", "Success criteria", "partial", "contract budget, eval/summary.json", "budget and gate targets are enforced; numeric quality targets were not pre-registered before the runs."),
    ("2 Prompts", "Role / persona", "full", "agents.py::SYSTEM", "one role prompt per agent."),
    ("2 Prompts", "Instructions", "full", "prompts.py, MCP prompts", "APPEAL_LETTER and RED_TEAM_REVIEW served by the MCP server."),
    ("2 Prompts", "Constraints / guardrails", "full", "prompts.py rules 0-8 + harness.verify", "every rule re-checked by code."),
    ("2 Prompts", "Output format", "full", "agents.py pydantic schemas", "with_structured_output: IntakeOut, Plan, RetrieverOut, CriteriaOut, AppealDraft, RedTeam."),
    ("2 Prompts", "Examples / skills", "partial", "prompts.py", "inline citation examples only; no skill library."),
    ("3 LLM", "Model choice", "full", "config.py::get_llm", "gpt-4o-mini only (Vocareum or Azure OpenAI); other model names refused."),
    ("3 LLM", "Context window", "partial", "contract budget", "token budget and argument limits; no per-slot inspector."),
    ("3 LLM", "Cost", "full", "harness.py::price", "cost in every receipt; budget per run."),
    ("3 LLM", "Latency", "full", "spans, receipt latency_s", "wall clock budget 240 s; 38-65 s live."),
    ("3 LLM", "Temperature", "full", "contract temperature=0", "passed to ChatOpenAI / AzureChatOpenAI."),
    ("3 LLM", "Top-p", "full", "contract top_p=1.0", "passed to the client."),
    ("4 Tools", "Web & data APIs", "full", "retrieval.py::azure_search, guard.py::prompt_shields, fetch_data.py", "Azure AI Search + Content Safety REST (env-gated), CMS Coverage API and public downloads at ingest."),
    ("4 Tools", "Custom tools", "full", "tools.py", "14 pure tool functions."),
    ("4 Tools", "MCP", "full", "mcp_server/claimguard_mcp_server.py", "14 tools, 8 resources (2 templates), 3 prompts; stdio + streamable HTTP with bearer auth."),
    ("4 Tools", "AI agent as a tool", "missing", "-", "not in v0.1."),
    ("5 Memory", "Working memory", "full", "CaseState", "LangGraph state."),
    ("5 Memory", "Episodic memory", "partial", "eval/logs + garden.py", "mined offline, not recalled."),
    ("5 Memory", "Vector database", "full", "FAISS IndexFlatIP; Azure AI Search vector index", "scripts/azure_search_index.py builds the index."),
    ("5 Memory", "SQL database", "out of scope", "-", "parquet snapshot + pandas; no relational store needed."),
    ("5 Memory", "File storage", "full", "data/snapshot, storage.py (Blob)", "checksummed snapshot; receipts to Blob or local."),
    ("6 Orchestration", "Framework (LangGraph)", "full", "agents.py::build_graph", "StateGraph with conditional edges."),
    ("6 Orchestration", "Triggers", "partial", "app.py, api/main.py, cli.py", "UI, REST and CLI; no schedule / webhook."),
    ("6 Orchestration", "Message queue", "missing", "-", "not in v0.1."),
    ("6 Orchestration", "Agent2Agent", "missing", "-", "not in v0.1."),
    ("6 Orchestration", "Error handling", "full", "agents.py, retrieval.py, storage.py, guard.py", "LLM retries, tool errors as data, budget stops, every Azure adapter falls back locally."),
    ("7 Interface", "Chat interface", "missing", "-", "form-based Streamlit UI, no chat."),
    ("7 Interface", "Web app", "full", "app.py", "8 tabs with human sign-off."),
    ("7 Interface", "API endpoint", "full", "api/main.py", "FastAPI with X-API-Key: appeals, sign-off, receipt verify."),
    ("7 Interface", "Slack / Discord bot", "out of scope", "-", "not shipped."),
    ("8 Testing", "Unit tests", "full", "tests/ (71)", "mock LLM through the real graph + MCP subprocess; ci/ci.yml ready to add."),
    ("8 Testing", "Latency tests", "full", "eval/logs, receipts", "latency per run and per span."),
    ("8 Testing", "Quality metrics", "full", "scripts/run_eval.py", "recall@k, MRR, gate mutation catch rate, citation validity, injection block / false-positive rate, AUC, Brier."),
    ("8 Testing", "Improvement loop", "full", "scripts/garden.py, CHANGELOG", "failure patterns -> proposals -> human fix -> re-run (documented for 3f04269)."),
]

LG = [
    ("Client", "Web UI", "full", "app.py", "Streamlit."),
    ("Client", "Mobile App", "out of scope", "-", "web UI and REST only."),
    ("Client", "API Request", "full", "api/main.py", "JSON with X-API-Key."),
    ("API Gateway", "FastAPI", "full", "api/main.py", "auth, pydantic validation, sign-off, receipt verify."),
    ("LangGraph Agent System", "Planner Node", "full", "agents.py::planner", "LLM Plan."),
    ("LangGraph Agent System", "Executor Node", "full", "agents.py::orchestrator + specialists", "code-enforced router over 5 specialists."),
    ("LangGraph Agent System", "Validator Node", "full", "agents.py::verifier + gate", "red team + 12 checks + gate + receipt."),
    ("LangGraph Agent System", "Agent State Machine", "full", "agents.py::CaseState", "typed state, conditional edges, recursion limit."),
    ("MCP Server", "Tool Registry", "full", "resource registry://tools", "call counters, server-side limits and recent refusals."),
    ("MCP Server", "Memory Access", "partial", "resources imr://case/{id}, policy://ncd/{id}, dataset://manifest", "read access to case and policy records; no agent memory by design."),
    ("MCP Server", "Policy Engine", "full", "server_policy.py::ServerPolicy.guard", "re-checks limits on every tools/call; refusals logged."),
    ("Data & Memory Layer", "Redis (cache)", "out of scope", "-", "in-process caches (lru_cache, joblib)."),
    ("Data & Memory Layer", "PostgreSQL (database)", "out of scope", "-", "parquet snapshot; Blob for receipts."),
    ("Data & Memory Layer", "Vector Store (embeddings)", "full", "FAISS + Azure AI Search", "local and cloud vector indexes."),
    ("Deployment & LLM Infrastructure", "Docker / Compose", "full", "Dockerfile, docker-compose.yml", "app + API + HTTP MCP server."),
    ("Deployment & LLM Infrastructure", "Kubernetes", "partial", "infra/resources.bicep (Azure Container Apps)", "managed, Kubernetes-based Container Apps; no raw k8s manifests."),
    ("Deployment & LLM Infrastructure", "vLLM", "out of scope", "-", "only gpt-4o-mini via Vocareum / Azure OpenAI."),
]


def status_line(statuses: list[str]) -> str:
    c = Counter(statuses)
    return ", ".join(f"{c[s]} {s}" for s in ("full", "partial", "missing", "out of scope") if c[s])


def main() -> None:
    kg_rows = [r for rows in KG.values() for r in rows]
    assert len(kg_rows) == 34 and len(BUILD) == 37 and len(LG) == 17, (len(kg_rows), len(BUILD), len(LG))
    out = ["# ClaimGuard coverage vs the course diagrams", "",
           "Generated by `scripts/build_coverage.py`. Statuses: **full** (implemented and tested), **partial** (implemented with a stated limit), "
           "**missing** (not in v0.1), **out of scope** (deliberately not built). Nothing is claimed that the code does not do.", "",
           f"## Agentic-AI knowledge graph (34 nodes): {status_line([r[1] for r in kg_rows])}", ""]
    for sec, rows in KG.items():
        out += [f"### {sec}", "", "| Node | Status | File / function | How it works | Evidence |", "|---|---|---|---|---|"]
        out += [f"| {n} | {s} | `{f}` | {h} | {e} |" for n, s, f, h, e in rows] + [""]
    out += [f"## AI Agent build diagram (8 boxes, 37 items): {status_line([r[2] for r in BUILD])}", "",
            "| Box | Item | Status | File / function | How it works |", "|---|---|---|---|---|"]
    out += [f"| {b} | {i} | {s} | `{f}` | {h} |" for b, i, s, f, h in BUILD] + [""]
    out += [f"## LangGraph + MCP architecture (17 components): {status_line([r[2] for r in LG])}", "",
            "| Layer | Component | Status | File / function | How it works |", "|---|---|---|---|---|"]
    out += [f"| {lay} | {c} | {s} | `{f}` | {h} |" for lay, c, s, f, h in LG] + [""]
    out += ["## Required by the capstone brief", "",
            "| Requirement | Where |", "|---|---|",
            "| LangChain | structured output, bind_tools, BaseRetriever (`PolicyRetriever`), text splitter, langchain-mcp-adapters |",
            "| LangGraph | `claimguard/agents.py::build_graph` StateGraph |",
            "| Live MCP | `mcp_server/` over stdio and streamable HTTP; `scripts/verify_mcp.py` |",
            "| Azure AI Foundry | AzureChatOpenAI provider + `infra/` Foundry resource, project and gpt-4o-mini deployment (not yet deployed) |",
            "| Public dataset | CMS NCD, CA DMHC IMR, NY DFS (docs/DATA_SOURCES.md) |", ""]
    (ROOT / "docs" / "COVERAGE.md").write_text("\n".join(out), encoding="utf-8")
    print("KG:", status_line([r[1] for r in kg_rows]), "| build:", status_line([r[2] for r in BUILD]), "| LG:", status_line([r[2] for r in LG]))


if __name__ == "__main__":
    main()
