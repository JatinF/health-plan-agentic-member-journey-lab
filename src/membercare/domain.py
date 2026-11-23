"""Deterministic journey facts. These functions do not call a model."""

from __future__ import annotations

import re

from membercare.errors import LabError

_EOB_ID = re.compile(r"\b(?:DEMO-PT-OLD|DEMO-PT-\d{2}|DEMO-\d{4}|OTHER-\d{4})\b", re.I)


def named_eob_id(question: str) -> str | None:
    match = _EOB_ID.search(question)
    return None if match is None else match.group(0).upper()


def classify(question: str) -> str:
    text = question.lower()
    if "billing review" in text or ("open" in text and "review" in text):
        return "action"
    if "cardiology" in text or "in-network" in text or "provider" in text:
        return "care"
    if "physical therapy" in text or "how many visits" in text:
        return "benefits"
    if any(word in text for word in ("claim", "eob", "owe", "copay", "partial")):
        return "claims"
    if "deductible" in text and any(word in text for word in ("visit", "paid")):
        return "claims"
    return "clarify"


def benefits_facts(section: dict, coverage: dict, eobs: list[dict]) -> dict:
    facts = section["facts"]
    if coverage["status"] != "active":
        raise LabError("inconsistent", "coverage is not active")
    counted: list[str] = []
    outside: list[str] = []
    for eob in eobs:
        if eob["service_category"] != "physical-therapy":
            continue
        if eob["amounts"]["copay"] != facts["copay_cents"]:
            raise LabError("inconsistent", "physical therapy copay does not match the plan guide")
        year = str(eob["billable_end"])[:4]
        if year != str(section["plan_year"]):
            outside.append(eob["id"])
            continue
        counted.append(eob["id"])
    used = len(counted)
    limit = int(facts["visit_limit"])
    return {
        "kind": "benefits",
        "covered": bool(facts["covered"]),
        "visit_limit": limit,
        "used": used,
        "remaining": max(limit - used, 0),
        "outside_year": outside,
        "copay_cents": int(facts["copay_cents"]),
        "section_id": section["id"],
        "document_title": section["document_title"],
        "plan_name": section["plan_name"],
        "plan_year": section["plan_year"],
        "coverage_id": coverage["id"],
        "eob_ids": counted,
    }


def select_claim(question: str, eobs: list[dict]) -> tuple[dict, str]:
    if not eobs:
        raise LabError("not_found", "no explanations of benefits are on file")
    text = question.lower()
    named = named_eob_id(question)
    if named:
        for eob in eobs:
            if eob["id"].upper() == named:
                return eob, "named"
        raise LabError("not_found", "that explanation of benefits was not found")
    ordered = sorted(eobs, key=lambda item: item["billable_end"])
    if "partial" in text:
        partials = [eob for eob in ordered if eob["amounts"]["coinsurance"] > 0]
        if not partials:
            partials = [
                eob
                for eob in ordered
                if eob["amounts"]["submitted"] > eob["amounts"]["eligible"]
                and eob["service_category"] != "urgent-care"
            ]
        if not partials:
            raise LabError("not_found", "no partially paid explanation of benefits was found")
        return partials[-1], "partial"
    if "urgent" in text:
        urgent = [eob for eob in ordered if eob["service_category"] == "urgent-care"]
        if not urgent:
            raise LabError("not_found", "no urgent care explanation of benefits was found")
        return urgent[-1], "urgent"
    return ordered[-1], "latest"


def claims_facts(question: str, section: dict, calc_section: dict, eobs: list[dict]) -> dict:
    eob, selection = select_claim(question, eobs)
    amounts = eob["amounts"]
    if eob["service_category"] == "urgent-care":
        guide_copay = section["facts"].get("copay_cents")
        if guide_copay != amounts["copay"]:
            raise LabError("inconsistent", "urgent care copay does not match the plan guide")
        cited = section
    else:
        cited = calc_section
    percent = int(calc_section["facts"]["coinsurance_percent"])
    base = amounts["eligible"] - amounts["deductible"]
    expected = base * percent // 100
    partial = amounts["submitted"] > amounts["eligible"]
    return {
        "kind": "claims",
        "eob_id": eob["id"],
        "service_category": eob["service_category"],
        "billable_end": eob["billable_end"],
        "selection": selection,
        "partial": partial,
        "section_id": cited["id"],
        "document_title": cited["document_title"],
        "coinsurance_percent": percent,
        "coinsurance_matches_guide": amounts["coinsurance"] == expected,
        "amounts": amounts,
        "copay_cents": amounts["copay"],
        "deductible_cents": amounts["deductible"],
        "coinsurance_cents": amounts["coinsurance"],
        "benefit_cents": amounts["benefit"],
        "member_owes_cents": amounts["member_owes"],
        "submitted_cents": amounts["submitted"],
        "eligible_cents": amounts["eligible"],
    }


def care_facts(section: dict, providers: list[dict]) -> dict:
    return {
        "kind": "care",
        "section_id": section["id"],
        "document_title": section["document_title"],
        "plan_name": section["plan_name"],
        "copay_cents": int(section["facts"]["copay_cents"]),
        "referral_required": bool(section["facts"]["referral_required"]),
        "providers": providers,
    }
