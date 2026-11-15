# Gumroad listing draft - ClaimGuard

> Draft copy for the seller to paste into Gumroad. Prices are suggestions. Nothing here has been published.
> It makes no testimonials, no user counts and no claims about appeal success rates, because none exist.

## Title
ClaimGuard - Agentic RAG Starter Kit for Health-Insurance Appeals (LangGraph + MCP + Azure AI Foundry)

## Tagline
A working, tested codebase that drafts **cited** appeal letters from public Medicare policy and published review decisions. It checks every draft with 12 code-enforced gates and releases one only after a human signs off.

## Description
ClaimGuard is a complete Python codebase for health-insurance denial appeals:

- **Agents.** A LangGraph planner and orchestrator drive five specialist agents: Policy Retriever (ReAct), Criteria Matcher, Risk Analyst, Appeal Writer and a red-team Verifier.
- **MCP server.** Every agent works through a real Model Context Protocol server (stdio and streamable HTTP) with 14 tools, 8 resources and 3 prompts.
- **Citations.** Drafts cite CMS National Coverage Determinations and published California IMR decisions. Code checks that every citation exists and was retrieved, that quotes are verbatim and that every number is grounded.
- **Receipts and sign-off.** Each run ends with an HMAC-signed receipt that carries the git commit and contract hash. A named reviewer approves or rejects the draft in the UI or API.

It runs on gpt-4o-mini through any OpenAI-compatible endpoint or Azure OpenAI. Bicep and azd files provision Azure AI Foundry, AI Search, Storage, Key Vault, Container Apps and App Insights.

It is built for health-tech developers, patient-advocacy and revenue-cycle teams prototyping appeal tooling, and AI engineers and educators who want an inspectable, safety-first agent pattern.

## What is inside
- LangGraph multi-agent graph with budgets (calls, tokens, cost, wall clock) from a hashed contract.
- MCP server (official SDK, FastMCP) over stdio and HTTP with bearer auth and a server-side policy engine.
- Hybrid retrieval (BM25 + LSA/FAISS, RRF) with an Azure AI Search adapter and index loader.
- Calibrated overturn model (time split, test ROC-AUC 0.756 on 2025), a text model, and statistics with effect sizes.
- Streamlit app (8 tabs: draft, evidence, risk model, stats, checks and receipt, monitoring, coverage, about) plus FastAPI and a CLI.
- 71 offline tests (mock LLM), ruff + mypy clean, an evaluation script, and a ready-to-add GitHub Actions workflow.
- A public-data snapshot with checksums and a cleaning log; no synthetic or patient data.

## Who it is not for
- It is not a filing service, legal advice or medical advice, and it does not predict whether any appeal will win.
- It is not a turnkey SaaS. You bring your own model endpoint and, for Azure, your own subscription.

## Suggested pricing
- Starter (code + docs): $49.
- Team (plus a 30-minute setup call): $149.

## FAQ
- **Does it need Azure?** No. It runs locally with any OpenAI-compatible gpt-4o-mini endpoint, and Azure is optional.
- **What does a run cost?** About $0.003-0.005 at gpt-4o-mini list price (8-10 calls).
- **Can I use my own policies?** Yes. Replace the snapshot builder or load your documents into the Azure AI Search index, keeping the same chunk-id format.
- **License:** the code is MIT. Data stays under its sources' terms (see DATA_SOURCES.md).
