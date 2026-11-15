"""ClaimGuard MCP server - official `mcp` Python SDK (FastMCP), over stdio AND streamable HTTP.

    python mcp_server/claimguard_mcp_server.py                                  # stdio (the app and CI launch it as a subprocess)
    python mcp_server/claimguard_mcp_server.py --transport streamable-http --port 8765   # HTTP at http://127.0.0.1:8765/mcp

HTTP auth: when CG_MCP_TOKEN is set, every HTTP request must send "Authorization: Bearer <token>" (Container Apps sets it
from Key Vault). The server never receives LLM keys (the client strips them from the environment).

Tools      parse_denial, get_imr_case, get_dfs_case, search_coverage_policy, get_ncd, match_coverage_criteria, search_imr_precedent,
           score_overturn_likelihood, classify_request_text, cohort_stats, hypothesis_tests, graph_neighbors, scan_documents,
           confirm_red_team
Resources  policy://ncd/{ncd_id}, imr://case/{reference_id}, disclaimer://not-advice, model://overturn-card, dataset://manifest,
           policy://contract, registry://tools, graph://coverage-graph
Prompts    appeal_letter, red_team_review, garden_review
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from claimguard import tools as T  # noqa: E402
from claimguard.config import CONTRACT_PATH  # noqa: E402
from claimguard.prompts import APPEAL_LETTER, DISCLAIMER, GARDEN_REVIEW, RED_TEAM_REVIEW  # noqa: E402
from claimguard.server_policy import ServerPolicy  # noqa: E402

mcp = FastMCP("claimguard", log_level="WARNING")
policy = ServerPolicy()


def _j(obj) -> str:
    return json.dumps(obj, indent=1, default=str)


@mcp.tool()
@policy.guard("parse_denial")
def parse_denial(text: str) -> str:
    """Deterministic first-pass parse of a de-identified denial: service, denial basis, plan type, public ids and code mentions."""
    return _j(T.parse_denial(text))


@mcp.tool()
@policy.guard("get_imr_case")
def get_imr_case(reference_id: str, include_outcome: bool = False) -> str:
    """One published CA DMHC IMR row by ReferenceID (e.g. MN25-45854). The outcome and Findings are withheld from agents."""
    return _j(T.get_imr_case(reference_id, include_outcome))


@mcp.tool()
@policy.guard("get_dfs_case")
def get_dfs_case(case_number: str) -> str:
    """One published NY DFS external appeal by Case Number (e.g. 201906-117724)."""
    return _j(T.get_dfs_case(case_number))


@mcp.tool()
@policy.guard("search_coverage_policy")
def search_coverage_policy(query: str, k: int = 4, mode: str = "hybrid") -> str:
    """Hybrid (BM25 + vector, RRF) search over current CMS NCD text (Azure AI Search when configured). Returns excerpt ids like NCD-280.14:3."""
    return _j(T.search_coverage_policy(query, k, mode))


@mcp.tool()
@policy.guard("get_ncd")
def get_ncd(ncd_id: str) -> str:
    """Metadata, chunk ids and a preview of one current National Coverage Determination (e.g. 280.14 or NCD-280.14)."""
    return _j(T.get_ncd(ncd_id))


@mcp.tool()
@policy.guard("match_coverage_criteria")
def match_coverage_criteria(chunk_ids: list[str], facts: list[str]) -> str:
    """Split policy excerpts into criterion sentences; mark related_case_fact or needs_documentation (never 'met')."""
    return _j(T.match_coverage_criteria(chunk_ids, facts))


@mcp.tool()
@policy.guard("search_imr_precedent")
def search_imr_precedent(query: str, k: int = 4, before_year: int | None = None, exclude_id: str | None = None,
                         treatment_category: str | None = None) -> str:
    """Similar published CA DMHC IMR decisions (only years before `before_year`, never `exclude_id`)."""
    return _j(T.search_imr_precedent(query, k, before_year, exclude_id, treatment_category))


@mcp.tool()
@policy.guard("score_overturn_likelihood")
def score_overturn_likelihood(DiagnosisCategory: str, DiagnosisSubCategory: str, TreatmentCategory: str, TreatmentSubCategory: str,
                              Type: str, IMRType: str, AgeRange: str = "Unknown", PatientGender: str = "Unknown") -> str:
    """P3 time-split classifier: calibrated probability that a published IMR with these pre-decision fields overturned the plan."""
    return _j(T.score_overturn_likelihood(DiagnosisCategory, DiagnosisSubCategory, TreatmentCategory, TreatmentSubCategory, Type, IMRType,
                                          AgeRange, PatientGender))


@mcp.tool()
@policy.guard("classify_request_text")
def classify_request_text(text: str) -> str:
    """P4 TF-IDF + logistic regression on the request sentence only (pre-decision text)."""
    return _j(T.classify_request_text(text))


@mcp.tool()
@policy.guard("cohort_stats")
def cohort_stats(treatment_category: str | None = None, review_type: str | None = None, diagnosis_category: str | None = None,
                 before_year: int | None = None) -> str:
    """P2 descriptive overturn rate (Wilson 95% CI) of published IMRs matching the filters."""
    return _j(T.cohort_stats(treatment_category, review_type, diagnosis_category, before_year))


@mcp.tool()
@policy.guard("hypothesis_tests")
def hypothesis_tests() -> str:
    """P2 hypothesis tests (chi-square, Cochran-Armitage trend, two-proportion CA vs NY) with effect sizes."""
    return _j(T.hypothesis_tests())


@mcp.tool()
@policy.guard("graph_neighbors")
def graph_neighbors(treatment_subcategory: str, k: int = 5) -> str:
    """Coverage-graph neighbours of a treatment subcategory: diagnosis categories (with overturn rates) and policy documents."""
    return _j(T.graph_neighbors(treatment_subcategory, k))


@mcp.tool()
@policy.guard("scan_documents")
def scan_documents(texts: list[str]) -> str:
    """Indirect prompt-injection scan of retrieved texts (deterministic scanner + Azure Prompt Shields when configured)."""
    return _j(T.scan_documents(texts))


@mcp.tool()
@policy.guard("confirm_red_team")
def confirm_red_team(issues_json: str, draft: str) -> str:
    """Keep only red-team issues whose quoted sentence really occurs in the draft."""
    try:
        issues = json.loads(issues_json)
    except Exception:
        return _j({"error": "issues_json must be a JSON list"})
    return _j(T.confirm_red_team(issues, draft))


# ----------------------------------------------------------------------------- resources
@mcp.resource("policy://ncd/{ncd_id}")
def ncd_resource(ncd_id: str) -> str:
    """Read-only snapshot of one current NCD."""
    return _j(T.get_ncd(ncd_id))


@mcp.resource("imr://case/{reference_id}")
def imr_resource(reference_id: str) -> str:
    """Read-only published IMR row (outcome withheld)."""
    return _j(T.get_imr_case(reference_id, False))


@mcp.resource("disclaimer://not-advice")
def disclaimer() -> str:
    """The required not-legal / not-medical-advice text."""
    return DISCLAIMER


@mcp.resource("model://overturn-card")
def model_card() -> str:
    """P3 model card: features, split, test metrics, baselines, calibration and limits."""
    return _j(T.model_card())


@mcp.resource("dataset://manifest")
def dataset_manifest() -> str:
    """Sources, licenses, checksums and the cleaning log of the committed snapshot."""
    return _j(T.dataset_card())


@mcp.resource("policy://contract")
def contract() -> str:
    """The run contract (budgets, required checks)."""
    return CONTRACT_PATH.read_text(encoding="utf-8")


@mcp.resource("registry://tools")
def registry() -> str:
    """Tool registry with call counters and recent server-side refusals."""
    return _j({"tools": sorted(policy.counters) or [], "counters": policy.counters, "recent_refusals": policy.refusals[-10:],
               "limits": policy.limits})


@mcp.resource("graph://coverage-graph")
def coverage_graph() -> str:
    """Schema of the coverage graph and one example neighbourhood."""
    return _j({"schema": {"nodes": ["treatment_subcategory", "diagnosis_category", "policy_document"],
                          "edges": ["treatment->diagnosis (IMR co-occurrence, overturn rate)", "treatment->policy (hybrid retrieval)"]},
               "example": T.graph_neighbors("Insulin Pump", 3)})


# ----------------------------------------------------------------------------- prompts
@mcp.prompt()
def appeal_letter(case_json: str, policy_text: str, criteria_json: str, precedents_json: str, risk_json: str, risk_percent: str,
                  revision_note: str = "") -> str:
    """Draft only from tool facts; cite excerpt ids; verbatim quotes; include the model signal as a signal."""
    return APPEAL_LETTER.format(case_json=case_json, policy_text=policy_text, criteria_json=criteria_json, precedents_json=precedents_json,
                                risk_json=risk_json, risk_percent=risk_percent, revision_note=revision_note)


@mcp.prompt()
def red_team_review(case_json: str, draft: str) -> str:
    """Checklist used by the verifier; its issues are confirmed by confirm_red_team."""
    return RED_TEAM_REVIEW.format(case_json=case_json, draft=draft)


@mcp.prompt()
def garden_review(patterns_json: str, required_checks_json: str) -> str:
    """Gardener: propose (never apply) one improvement per recurring failure pattern."""
    return GARDEN_REVIEW.format(patterns_json=patterns_json, required_checks_json=required_checks_json)


def http_app():
    """Streamable-HTTP ASGI app with optional bearer-token auth (CG_MCP_TOKEN)."""
    app = mcp.streamable_http_app()
    token = os.environ.get("CG_MCP_TOKEN")
    if not token:
        return app
    import hmac

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class Bearer(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            auth = request.headers.get("authorization", "")
            if not hmac.compare_digest(auth, f"Bearer {token}"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app.add_middleware(Bearer)
    return app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    ap.add_argument("--host", default=os.environ.get("CG_MCP_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("CG_MCP_PORT", "8765")))
    a = ap.parse_args()
    if a.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn
        uvicorn.run(http_app(), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
