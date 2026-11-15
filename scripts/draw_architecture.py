"""Draw docs/architecture.png (matplotlib).   python scripts/draw_architecture.py

Tool / resource / prompt counts and the required checks are read from the MCP server source and contract.json,
so the figure cannot drift from the code (the script asserts the counts)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
SRV = (ROOT / "mcp_server" / "claimguard_mcp_server.py").read_text(encoding="utf-8")
K = json.loads((ROOT / "contract.json").read_text(encoding="utf-8"))
TOOLS = re.findall(r"@mcp\.tool\(\)\s*\n@policy\.guard\(\"(\w+)\"\)", SRV)
RES = re.findall(r'@mcp\.resource\("([^"]+)"', SRV)
PROMPTS = re.findall(r"@mcp\.prompt\(\)\s*\ndef (\w+)", SRV)
assert len(TOOLS) == 14 and len(RES) == 8 and len(PROMPTS) == 3, (TOOLS, RES, PROMPTS)
CHECKS = K["required_checks"]
B = K["budget"]

C = {"ui": "#e8f0fe", "guard": "#fde7e7", "llm": "#fff4d6", "rule": "#e6f4ea", "mcp": "#efe7fb", "data": "#f1f3f4", "az": "#e0f2ff", "obs": "#e0f7fa"}
fig, ax = plt.subplots(figsize=(18, 12.5))
ax.set_xlim(0, 180)
ax.set_ylim(0, 125)
ax.axis("off")


def box(x, y, w, h, title, body="", color="#fff", fs=9.5, bfs=7.4, ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.35,rounding_size=1.1", fc=color, ec="#333", lw=1.1, ls=ls))
    ax.text(x + w / 2, y + h - 1.2, title, ha="center", va="top", fontsize=fs, weight="bold")
    if body:
        ax.text(x + w / 2, y + h - 1.2 - 2.6 * (title.count("\n") + 1), body, ha="center", va="top", fontsize=bfs, linespacing=1.25)


def arrow(x1, y1, x2, y2, label="", color="#333", ls="-", rad=0.0, both=False, lx=0.0, ly=0.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="<|-|>" if both else "-|>", mutation_scale=11, color=color, lw=1.1, ls=ls,
                                 connectionstyle=f"arc3,rad={rad}"))
    if label:
        ax.text((x1 + x2) / 2 + lx, (y1 + y2) / 2 + ly, label, fontsize=6.9, ha="center", va="center", color=color, bbox=dict(fc="white", ec="none", pad=0.25))


ax.text(90, 123, "ClaimGuard v0.1: cited appeal drafts + denial-risk briefs (LangGraph agents + live MCP + Azure AI Foundry, gpt-4o-mini)",
        ha="center", fontsize=13, weight="bold")

# Row 1: clients
box(4, 104, 40, 13, "Streamlit app (app.py)", "8 tabs: Appeal draft, Evidence, Risk model,\nStats, Checks & receipt, Monitoring,\nCoverage matrix, About + human sign-off", C["ui"])
box(50, 104, 34, 13, "FastAPI (api/main.py)", "/v1/appeals, /signoff, /receipts/verify\nX-API-Key (Key Vault secret)", C["ui"])
box(90, 104, 30, 13, "CLI (python -m claimguard)", "cases, search, score, stats,\nrun, verify-receipt, monitor, mcp", C["ui"])
box(126, 104, 50, 13, "Run contract (contract.json)", f"SHA-256 hashed before the first token\nbudget: {B['max_llm_calls']} LLM calls, {B['max_tool_calls']} tool calls, ${B['max_cost_usd']}\nper-agent tool allow-lists, arg limits", C["rule"])

# Row 2: LangGraph
box(4, 56, 172, 43, "", "", "#fbfbfb", ls="--")
ax.text(8, 97.6, "LangGraph StateGraph (claimguard/agents.py)  -  code-enforced router follows the planner's plan; max 1 revision", fontsize=9.5, weight="bold")
box(7, 80, 24, 13, "input_guard", "regex injection + PHI\nscope refusals\nPrompt Shields (Azure)", C["guard"])
box(35, 80, 18, 13, "intake", "LLM structured\nIntakeOut", C["llm"])
box(57, 80, 18, 13, "planner", "LLM Plan\n(steps + watch-outs)", C["llm"])
box(79, 80, 22, 13, "orchestrator", "deterministic\nrouter + budget", C["rule"])
box(7, 60, 30, 15, "policy_retriever", "ReAct: bind_tools ->\nsearch_coverage_policy, get_ncd\n+ document injection scan", C["llm"])
box(41, 60, 26, 15, "criteria_matcher", "match_coverage_criteria\n-> needs_documentation\n(never 'met')", C["llm"])
box(71, 60, 26, 15, "risk_analyst (MCP)", "score_overturn (P3)\nclassify_request (P4)\ncohort_stats (P2), precedents", C["rule"])
box(101, 60, 30, 15, "appeal_writer", "MCP prompt -> AppealDraft\ncode renders brief numbers\nwriter pre-check (11 checks)", C["llm"])
box(135, 60, 38, 15, "verifier / red team", "LLM proposes issues ->\nconfirm_red_team (code confirms)\nverify(): 12 checks PASS/FAIL/NOT_RUN", C["guard"])
box(135, 80, 38, 13, "gate (finalize)", "blocked_unrun | not_finalized |\nawaiting_human_signoff | refused\nHMAC receipt: git_sha + contract sha", C["rule"])
arrow(31, 86.5, 35, 86.5)
arrow(53, 86.5, 57, 86.5)
arrow(75, 86.5, 79, 86.5)
for x in (22, 54, 84, 116, 154):
    arrow(90, 80, x, 75, color="#555", rad=0.0)
arrow(154, 75, 154, 80, "all checks run")
arrow(19, 93.4, 150, 93.4, "refused before any LLM call", color="#b00020", ls="--", rad=-0.04, ly=2.6)

# Row 3: MCP + checks
box(4, 30, 84, 22, "MCP server (mcp_server/claimguard_mcp_server.py)\nstdio AND streamable HTTP (bearer token)",
    f"{len(TOOLS)} tools: " + ", ".join(TOOLS[:7]) + ",\n" + ", ".join(TOOLS[7:]) + f"\n{len(RES)} resources: " + ", ".join(RES[:4]) + ",\n"
    + ", ".join(RES[4:]) + f"\n{len(PROMPTS)} prompts: " + ", ".join(PROMPTS) + "\nServerPolicy re-validates k, query length, outcome access", C["mcp"], bfs=7.0)
box(92, 30, 84, 22, "Required checks (claimguard/harness.py) + release", ", ".join(CHECKS[:6]) + ",\n" + ", ".join(CHECKS[6:])
    + "\nNOT_RUN never counts as PASS -> blocked_unrun\nrelease check: human_signoff (named reviewer re-signs the receipt)", C["guard"], bfs=7.2)
arrow(46, 56, 46, 52, "langchain-mcp-adapters", both=True)
arrow(154, 56, 134, 52)

# Row 4: data + Azure
box(4, 3, 54, 22, "Public data (data/snapshot, manifest sha256)",
    "CMS NCD (345 current, 1,035 chunks) - US gov work\nCA DMHC IMR 42,710 decisions - CC BY (data.ca.gov)\nNY DFS external appeals 62,249 - public records\nLCD optional, local only (AMA CPT never committed)\nno synthetic data, no PHI", C["data"], bfs=7.2)
box(62, 3, 54, 22, "Retrieval + models (local fallback)",
    "BM25 + LSA/FAISS, RRF k=60 (LangChain retriever)\nprecedents: TF-IDF, decided before the case year\nP3 HistGB + calibration, time split (test 2025)\nP4 TF-IDF + LR on the request sentence\nP2 chi-square / trend / z-tests + effect sizes", C["rule"], bfs=7.2)
box(120, 3, 56, 22, "Azure AI Foundry adapters (env-gated)",
    "Azure OpenAI gpt-4o-mini (CG_LLM_PROVIDER=azure)\nAzure AI Search (hybrid + semantic)\nBlob Storage (receipts), Key Vault (secrets)\nContent Safety Prompt Shields, App Insights (OTel)\nContainer Apps; infra/main.bicep + azure.yaml", C["az"], bfs=7.2)
arrow(46, 30, 31, 25)
arrow(46, 30, 89, 25)
arrow(88, 41, 148, 25, "if AZURE_* set", color="#0b5cad", ls="--", rad=-0.1)
arrow(24, 104, 24, 99)
arrow(67, 104, 67, 99)
arrow(105, 104, 105, 99)
arrow(151, 104, 151, 99, "hashed into receipt")

out = ROOT / "docs" / "architecture.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out.relative_to(ROOT)}")
