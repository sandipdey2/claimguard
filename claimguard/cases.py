"""Demo cases built only from real published records: CA DMHC IMR rows (de-identified by DMHC) as the denial, and real
CMS NCD text as the policy. The published Determination is HELD OUT from the agents and only used afterwards to score
the risk signal; no field is invented, and no patient is created."""
from __future__ import annotations

import re

from .data import imr_case

DEMO_CASES = [
    {"reference_id": "MN25-45854", "expected_ncd": "NCD-280.14", "why": "insulin pump (NCD 280.14 Infusion Pumps)"},
    {"reference_id": "MN25-44606", "expected_ncd": "NCD-20.29", "why": "hyperbaric oxygen therapy (NCD 20.29)"},
    {"reference_id": "MN25-46141", "expected_ncd": "NCD-50.3", "why": "cochlear implant (NCD 50.3)"},
    {"reference_id": "MN25-45013", "expected_ncd": "NCD-100.1", "why": "gastric bypass (NCD 100.1 Bariatric Surgery)"},
    {"reference_id": "MN25-44467", "expected_ncd": "NCD-240.4", "why": "CPAP (NCD 240.4)"},
    {"reference_id": "EI25-46125", "expected_ncd": None, "why": "implantable CGM, experimental/investigational denial; no NCD names it"},
]
BASIS = {"Medical Necessity": "not medically necessary", "Experimental/Investigational": "experimental or investigational",
         "Urgent Care": "urgent care not covered"}


def denial_from_imr(reference_id: str) -> dict:
    """The denial as the public record states it, without the reviewer's decision or reasoning."""
    row = imr_case(reference_id)
    if row is None:
        raise KeyError(f"unknown IMR ReferenceID {reference_id}")
    service = row.get("request_text") or row.get("TreatmentSubCategory")
    text = (f"Published CA DMHC Independent Medical Review case {row['ReferenceID']} ({row['ReportYear']}). "
            f"The health plan denied a request for {service}. Denial type: {row['Type']} "
            f"(the plan considered it {BASIS.get(row['Type'], row['Type'])}). Diagnosis category: {row['DiagnosisCategory']} / "
            f"{row['DiagnosisSubCategory']}. Treatment category: {row['TreatmentCategory']} / {row['TreatmentSubCategory']}. "
            f"Review type: {row['IMRType']}. Age range: {row['AgeRange']}. Gender: {row['PatientGender']}.")
    case = {f: row[f] for f in ["ReferenceID", "ReportYear", "DiagnosisCategory", "DiagnosisSubCategory", "TreatmentCategory",
                                 "TreatmentSubCategory", "Type", "IMRType", "AgeRange", "PatientGender"]}
    case["request_text"] = service
    return {"denial_text": text, "case": case, "held_out": {"Determination": row["Determination"], "overturned": int(row["overturned"])}}


SERVICE_RX = re.compile(r"(?:request(?:ed)? for|denied (?:a request for |coverage for |authorization for )?|coverage (?:of|for))\s+([^.;]{4,200})", re.I)


def parse_denial(text: str) -> dict:
    """Deterministic first pass over a de-identified denial: service, denial basis, plan type hints, codes and public ids."""
    t = text or ""
    low = t.lower()
    m = SERVICE_RX.search(t)
    basis = ("experimental_investigational" if re.search(r"experimental|investigational", low) else
             "medical_necessity" if re.search(r"medical(ly)? necess", low) else
             "formulary_exception" if "formulary" in low else "step_therapy" if "step therapy" in low else
             "out_of_network" if "out-of-network" in low or "out of network" in low else "unknown")
    plan = ("medicare_advantage" if re.search(r"medicare advantage|part c", low) else "medicare" if "medicare" in low else
            "medicaid" if "medicaid" in low else "commercial_ca_dmhc" if "dmhc" in low else "unknown")
    return {"service": (m.group(1).strip() if m else ""), "denial_basis": basis, "plan_type": plan,
            "imr_reference_ids": sorted(set(re.findall(r"\b[A-Z]{2}\d{2}-\d{3,6}\b", t))),
            "ncd_mentions": sorted(set(re.findall(r"\bNCD\s?(\d{2,3}(?:\.\d+){1,2})\b", t))),
            "lcd_mentions": sorted(set(re.findall(r"\bL\d{5}\b", t))),
            "code_mentions": {"icd10": sorted(set(re.findall(r"\b[A-TV-Z]\d{2}(?:\.\d{1,4})?\b", t))),
                              "hcpcs_level2": sorted(set(re.findall(r"\b[A-V]\d{4}\b", t)))},
            "method": "regex first pass; the intake agent confirms with structured output"}
