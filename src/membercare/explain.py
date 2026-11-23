"""Member-facing sentences. Every dollar amount is formatted from integer cents."""

from __future__ import annotations

import re

from membercare.errors import LabError
from membercare.money import format_usd

_DOLLAR = re.compile(r"\$(\d+)(?:\.(\d{2}))?")


def dollars_in_text(text: str) -> list[int]:
    found = []
    for match in _DOLLAR.finditer(text):
        found.append(int(match.group(1)) * 100 + int(match.group(2) or 0))
    return found


def allowed_cents(facts: dict) -> set[int]:
    allowed: set[int] = set()
    for key, value in facts.items():
        if key.endswith("_cents") and isinstance(value, int):
            allowed.add(value)
    amounts = facts.get("amounts") or {}
    for value in amounts.values():
        if isinstance(value, int):
            allowed.add(value)
    return allowed


def guard_text(text: str, allowed: set[int]) -> str:
    extra = [cents for cents in dollars_in_text(text) if cents not in allowed]
    if extra:
        raise LabError("inconsistent", "narrative contains an amount that is not in the records")
    return text


def render(facts: dict, question: str = "") -> str:
    kind = facts.get("kind")
    if kind == "claims":
        text = _claims(facts, question)
    elif kind == "benefits":
        text = _benefits(facts)
    elif kind == "care":
        text = _care(facts)
    elif kind == "action":
        text = pending_text(facts)
    elif kind == "action_open":
        text = _opened(facts)
    elif kind == "action_rejected":
        text = _rejected(facts)
    elif kind == "clarify":
        text = (
            "I can help with benefits, a claim amount, or in-network providers. "
            "Ask one of those, and I will answer from the synthetic plan guide and explanation-of-benefit records."
        )
    elif kind == "denied":
        text = "I cannot answer that from the records this actor is allowed to read."
    else:
        raise LabError("invalid", "nothing to explain")
    return guard_text(text, allowed_cents(facts))


def pending_text(facts: dict) -> str:
    title = facts.get("document_title", "Synthetic 2026 Plan Guide")
    return (
        f"Billing review {facts['case_id']} for EOB {facts['eob_id']} is pending human approval. "
        "It has not been opened.\n\n"
        f"Sources: {title} §8.1 · EOB {facts['eob_id']}\n\n"
        "Approval required"
    )


def _source_line(facts: dict, *parts: str) -> str:
    title = facts["document_title"]
    section = facts["section_id"]
    body = " · ".join(parts)
    return f"Sources: {title} §{section} · {body}"


def _claims(facts: dict, question: str) -> str:
    amounts = facts["amounts"]
    asked = dollars_in_text(question)
    prefix = ""
    if asked and amounts["member_owes"] not in asked:
        prefix = f"The records show {format_usd(amounts['member_owes'])} for this visit. "
    if facts["service_category"] == "urgent-care" and amounts["coinsurance"] == 0 and amounts["deductible"]:
        body = (
            f"{prefix}In this example, your plan's urgent care copay is {format_usd(amounts['copay'])}, "
            f"and the explanation of benefits records another {format_usd(amounts['deductible'])} toward your deductible."
        )
    elif facts.get("partial"):
        match = (
            f"The coinsurance on the explanation of benefits matches {facts['coinsurance_percent']}% "
            "of the eligible amount after the deductible in the plan guide."
            if facts.get("coinsurance_matches_guide")
            else "The coinsurance amount below is the explanation-of-benefit amount."
        )
        body = (
            f"Claim {facts['eob_id']} was partially paid. "
            f"Of the {format_usd(amounts['submitted'])} submitted, {format_usd(amounts['eligible'])} was eligible. "
            f"The plan paid {format_usd(amounts['benefit'])}. "
            f"You owe {format_usd(amounts['member_owes'])}, made up of {format_usd(amounts['deductible'])} "
            f"toward the deductible and {format_usd(amounts['coinsurance'])} of coinsurance. {match}"
        )
    else:
        body = (
            f"{prefix}EOB {facts['eob_id']} records a member amount of {format_usd(amounts['member_owes'])}. "
            f"That is {format_usd(amounts['copay'])} copay, {format_usd(amounts['deductible'])} deductible, "
            f"and {format_usd(amounts['coinsurance'])} coinsurance. "
            f"The plan paid {format_usd(amounts['benefit'])}."
        )
    if facts.get("selection") == "latest":
        body = f"Your latest claim is EOB {facts['eob_id']}, dated {facts['billable_end']}. " + body
    lines = [
        body,
        "",
        _source_line(facts, f"EOB {facts['eob_id']}"),
        "",
        "Next action: Request a billing review",
        "Approval required",
    ]
    return "\n".join(lines)


def _benefits(facts: dict) -> str:
    if not facts["covered"]:
        body = "The plan guide section for physical therapy says it is not covered."
    else:
        outside = ""
        if facts["outside_year"]:
            count = len(facts["outside_year"])
            noun = "explanation of benefits is" if count == 1 else "explanations of benefits are"
            outside = f" {count} physical therapy {noun} outside plan year {facts['plan_year']} and is not counted."
        body = (
            f"Yes. Physical therapy is covered in network. {facts['plan_name']} allows {facts['visit_limit']} "
            f"visits in a calendar year, and {facts['used']} are recorded on your explanations of benefits, "
            f"so {facts['remaining']} remain. The in-network copay is {format_usd(facts['copay_cents'])} per visit."
            f"{outside}"
        )
    eobs = " · ".join(f"EOB {eob_id}" for eob_id in facts["eob_ids"])
    parts = [f"Coverage {facts['coverage_id']}"]
    if eobs:
        parts.append(eobs)
    return "\n".join([body, "", _source_line(facts, *parts)])


def _care(facts: dict) -> str:
    referral = "does not require a referral" if not facts["referral_required"] else "requires a referral"
    lines = [
        (
            f"In-network cardiology options for {facts['plan_name']} are listed below. "
            f"The specialist copay is {format_usd(facts['copay_cents'])}. This plan {referral}."
        ),
        "",
    ]
    for provider in facts["providers"]:
        lines.append(
            f"- {provider['organization']} — {provider['practitioner']} — "
            f"{provider['line']}, {provider['city']} — {provider['phone']}"
        )
    role_ids = " · ".join(f"PractitionerRole {provider['role_id']}" for provider in facts["providers"])
    lines.extend(["", _source_line(facts, role_ids)])
    return "\n".join(lines)


def _opened(facts: dict) -> str:
    title = facts["document_title"]
    return (
        f"Billing review {facts['case_id']} for EOB {facts['eob_id']} is open. "
        "A reviewer approved it before it was opened.\n\n"
        f"Sources: {title} §8.1 · EOB {facts['eob_id']}"
    )


def _rejected(facts: dict) -> str:
    return (
        f"Billing review {facts['case_id']} was not opened. The reviewer rejected the request.\n\n"
        f"Sources: {facts['document_title']} §8.1 · EOB {facts['eob_id']}"
    )
