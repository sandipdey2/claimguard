"""Offline test fixtures: a scripted fake gpt-4o-mini (no network) that exercises the real LangGraph graph and the real
MCP server over stdio."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CG_RUNTIME_DIR", str(ROOT / "data" / "runtime"))
for k in ("OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_SEARCH_ENDPOINT", "AZURE_CONTENT_SAFETY_ENDPOINT", "APPLICATIONINSIGHTS_CONNECTION_STRING",
          "AZURE_STORAGE_ACCOUNT_URL", "AZURE_STORAGE_CONNECTION_STRING", "CG_MCP_URL"):
    os.environ.pop(k, None)

USAGE = {"input_tokens": 900, "output_tokens": 150, "total_tokens": 1050}


def _human(msgs) -> str:
    return "\n".join(m.content for m in msgs if getattr(m, "type", "") == "human" and isinstance(m.content, str))


class FakeStructured:
    def __init__(self, llm, schema):
        self.llm, self.schema = llm, schema

    async def ainvoke(self, msgs):
        self.llm.calls.append(self.schema.__name__)
        parsed = self.schema(**self.llm.respond(self.schema.__name__, _human(msgs)))
        return {"raw": AIMessage(content="", usage_metadata=USAGE), "parsed": parsed, "parsing_error": None}


class FakeBound:
    def __init__(self, llm):
        self.llm = llm
        self.n = 0

    async def ainvoke(self, msgs):
        self.llm.calls.append("react")
        self.n += 1
        if self.n == 1:
            m = re.search(r"Denied service: (.+)", _human(msgs))
            q = m.group(1) if m else "coverage"
            return AIMessage(content="Thought: search the NCD text for the service.", usage_metadata=USAGE,
                             tool_calls=[{"name": "search_coverage_policy", "args": {"query": q[:120], "k": 4}, "id": "call_1"}])
        return AIMessage(content="Found the relevant excerpts.", usage_metadata=USAGE)


class FakeLLM:
    """Deterministic stand-in for gpt-4o-mini. ``mode`` changes the writer: good | bad_citation | invent_number."""

    def __init__(self, mode: str = "good"):
        self.mode = mode
        self.calls: list[str] = []
        self.writes = 0

    def with_structured_output(self, schema, include_raw=True):
        return FakeStructured(self, schema)

    def bind_tools(self, tools):
        return FakeBound(self)

    def respond(self, name: str, h: str) -> dict:
        if name == "IntakeOut":
            svc = re.search(r"denied a request for ([^.]+)\.", h)
            cat = re.search(r"Treatment category: ([^/]+) /", h)
            service = svc.group(1) if svc else "the requested service"
            return {"service": service, "denial_basis": "medical_necessity", "treatment_category": (cat.group(1).strip() if cat else "Pharmacy"),
                    "case_facts": [f"The plan denied {service}.", "Denial type: Medical Necessity."], "search_queries": [service[:80]],
                    "missing_information": ["clinical documentation"]}
        if name == "Plan":
            return {"steps": [{"agent": a, "goal": "do it"} for a in ["policy_retriever", "criteria_matcher", "risk_analyst", "appeal_writer", "verifier"]],
                    "watch_outs": []}
        if name == "RetrieverOut":
            ids = re.findall(r"'((?:NCD|LCD)-[^']+)'", h.split("Only ids from these:")[-1])
            return {"selected": [{"chunk_id": i, "relevance": "relevant"} for i in ids[:2]], "no_relevant_policy": not ids}
        if name == "CriteriaOut":
            m = re.search(r"match_coverage_criteria:\n(.*)", h, re.S)
            crit = json.loads(m.group(1)).get("criteria", []) if m else []
            return {"criteria": [{"chunk_id": c["chunk_id"], "criterion_quote": c["criterion"], "status": "needs_documentation", "note": "document it"}
                                 for c in crit[:2]]}
        if name == "AppealDraft":
            self.writes += 1
            pol = re.findall(r"^((?:NCD|LCD)-[\d.A-Z]+:\d+): (.+)$", h, re.M)
            cid, text = max(pol, key=lambda t: len(t[1])) if pol else ("NCD-280.14:3", "")
            quote = " ".join(text.split()[:18])
            pm = re.search(r'gives (\d+\.\d)%', h)
            pct = pm.group(1) if pm else "50.0"
            prec = re.search(r"PRECEDENTS[^\n]*\n(\[.*?\])\n", h, re.S)
            precs = json.loads(prec.group(1)) if prec else []
            if self.mode == "bad_citation":
                cid_cited = "NCD-999.9:1"
            else:
                cid_cited = cid
            args = [f"The plan denied the requested service as not medically necessary. The policy sets coverage criteria [{cid_cited}]."]
            if self.mode == "invent_number" and self.writes == 1:
                args.append("Studies show 97.3% of such appeals succeed.")
            return {"subject": "Appeal of a denied service", "service_requested": "the denied service", "denial_basis": "Medical necessity",
                    "opening": "I am writing as the patient's authorized representative to appeal this denial.", "arguments": args,
                    "policy_points": [{"citation_id": cid, "quote": quote, "relevance": "states the criteria"}],
                    "precedent_points": [{"reference_id": p["reference_id"], "summary": "A published IMR on a similar request."} for p in precs[:1]],
                    "requested_action": "Please reconsider and approve the request.",
                    "risk_statement": f"The overturn model gives {pct}% for published reviews with similar categories; this is a signal from past "
                                      "published reviews, not a prediction for this appeal.",
                    "reviewer_questions": ["Which clinical records document the criteria?", "Who signs the letter?"]}
        if name == "RedTeam":
            return {"verdict": "pass", "issues": []}
        raise KeyError(name)


@pytest.fixture
def fake_llm():
    return FakeLLM()
