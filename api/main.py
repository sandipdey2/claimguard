"""ClaimGuard HTTP API (FastAPI). Run: uvicorn api.main:app --port 8000

Auth: X-API-Key must equal CG_API_KEY (Key Vault secret in Azure) unless CG_API_ALLOW_ANON=1 (local demos only).
POST /v1/appeals                     run the agents on a de-identified denial or a published IMR ReferenceID
GET  /v1/appeals/{run_id}            the stored result
POST /v1/appeals/{run_id}/signoff    human reviewer approves or rejects (re-signs the receipt)
POST /v1/receipts/verify             verify an HMAC receipt
GET  /v1/cases                       the public demo cases
GET  /health                         liveness + which Azure adapters are configured (booleans only)
"""
from __future__ import annotations

import hmac
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Depends, FastAPI, Header, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from claimguard import __version__  # noqa: E402
from claimguard.cases import DEMO_CASES, denial_from_imr  # noqa: E402
from claimguard.config import azure_flags, provider, secret  # noqa: E402
from claimguard.harness import human_signoff, verify_receipt  # noqa: E402
from claimguard.storage import save_json  # noqa: E402

app = FastAPI(title="ClaimGuard API", version=__version__,
              description="Cited appeal-letter drafts and denial-risk briefs from public CMS policy and published IMR decisions. "
                          "Not legal or medical advice; human review required; never files an appeal.")
app.state.llm_factory = None            # tests inject a mock LLM here
RESULTS: dict[str, dict] = {}


def auth(x_api_key: str | None = Header(default=None)) -> None:
    if os.environ.get("CG_API_ALLOW_ANON") == "1":
        return
    key = secret("CG_API_KEY")
    if not key or not x_api_key or not hmac.compare_digest(x_api_key, key):
        raise HTTPException(401, "missing or invalid X-API-Key")


class AppealIn(BaseModel):
    request: str = Field(default="Draft an appeal letter and a denial-risk brief for this denied claim.", max_length=1000)
    denial_text: str | None = Field(default=None, max_length=6000, description="de-identified denial text (no names, IDs, dates of birth)")
    reference_id: str | None = Field(default=None, description="a published CA DMHC IMR ReferenceID, e.g. MN25-45854")


class SignoffIn(BaseModel):
    reviewer: str = Field(max_length=80)
    approved: bool
    note: str = Field(default="", max_length=300)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "provider": provider(), "azure_adapters": azure_flags()}


@app.get("/v1/cases", dependencies=[Depends(auth)])
def cases() -> list:
    return DEMO_CASES


@app.post("/v1/appeals", dependencies=[Depends(auth)])
async def create(body: AppealIn) -> dict:
    from claimguard.agents import run_case
    case = None
    denial = body.denial_text or ""
    if body.reference_id:
        try:
            d = denial_from_imr(body.reference_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        denial, case = d["denial_text"], d["case"]
    if not denial.strip():
        raise HTTPException(422, "give denial_text or reference_id")
    llm = app.state.llm_factory() if app.state.llm_factory else None
    st = await run_case(body.request, denial, case, llm=llm)
    fin = st["final"]
    out = {"run_id": st["ctx"]["run_id"], "status": fin["status"], "reason": fin["reason"], "draft_md": st.get("draft_md"),
           "check_status": fin["verification"].get("check_status"), "receipt": fin["receipt"], "cost": st["ctx"]["cost"],
           "latency_s": st["ctx"]["latency_s"]}
    RESULTS[out["run_id"]] = out
    out["stored"] = save_json(f"{out['run_id']}.json", fin["receipt"])
    return out


@app.get("/v1/appeals/{run_id}", dependencies=[Depends(auth)])
def get(run_id: str) -> dict:
    if run_id not in RESULTS:
        raise HTTPException(404, "unknown run_id")
    return RESULTS[run_id]


@app.post("/v1/appeals/{run_id}/signoff", dependencies=[Depends(auth)])
def signoff(run_id: str, body: SignoffIn) -> dict:
    if run_id not in RESULTS:
        raise HTTPException(404, "unknown run_id")
    try:
        rec = human_signoff(RESULTS[run_id]["receipt"], body.reviewer, body.approved, body.note)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    RESULTS[run_id]["receipt"], RESULTS[run_id]["status"] = rec, rec["status"]
    save_json(f"{run_id}_signoff.json", rec)
    return {"run_id": run_id, "status": rec["status"], "receipt": rec}


@app.post("/v1/receipts/verify", dependencies=[Depends(auth)])
def verify(receipt: dict) -> dict:
    return {"valid": verify_receipt(receipt)}
