"""Build the synthetic FHIR bundles and plan guides.

The JSON files under membercare/data are the records the lab serves.
Run this module to rewrite them from the definitions below.
"""

from __future__ import annotations

import json
from pathlib import Path

ADJUDICATION = "http://terminology.hl7.org/CodeSystem/adjudication"
CARIN = "http://hl7.org/fhir/us/carin-bb/CodeSystem/C4BBAdjudication"
CLAIM_TYPE = "http://terminology.hl7.org/CodeSystem/claim-type"
COVERAGE_CLASS = "http://terminology.hl7.org/CodeSystem/coverage-class"
SYNTHETIC = "https://synthetic.example"

DATA_DIR = Path(__file__).resolve().parent / "data"


def _adj(code: str, dollars: int, system: str = ADJUDICATION) -> dict:
    return {
        "category": {"coding": [{"system": system, "code": code}]},
        "amount": {"value": dollars, "currency": "USD"},
    }


def _eob(
    eob_id: str,
    patient_id: str,
    coverage_id: str,
    provider_id: str,
    insurer_id: str,
    when: str,
    created: str,
    service_code: str,
    service_display: str,
    service_category: str,
    amounts: dict[str, int],
) -> dict:
    rows = [
        _adj("submitted", amounts["submitted"]),
        _adj("eligible", amounts["eligible"]),
        _adj("benefit", amounts["benefit"]),
        _adj("copay", amounts["copay"]),
        _adj("deductible", amounts["deductible"]),
        _adj("coinsurance", amounts["coinsurance"], CARIN),
    ]
    return {
        "resourceType": "ExplanationOfBenefit",
        "id": eob_id,
        "identifier": [{"system": f"{SYNTHETIC}/eob", "value": eob_id}],
        "status": "active",
        "type": {"coding": [{"system": CLAIM_TYPE, "code": "professional"}]},
        "use": "claim",
        "patient": {"reference": f"Patient/{patient_id}"},
        "created": created,
        "insurer": {"reference": f"Organization/{insurer_id}"},
        "provider": {"reference": f"Organization/{provider_id}"},
        "outcome": "complete",
        "billablePeriod": {"start": when, "end": when},
        "insurance": [{"focal": True, "coverage": {"reference": f"Coverage/{coverage_id}"}}],
        "item": [
            {
                "sequence": 1,
                "productOrService": {
                    "coding": [
                        {
                            "system": "http://www.ama-assn.org/go/cpt",
                            "code": service_code,
                            "display": service_display,
                        }
                    ]
                },
                "servicedDate": when,
                "extension": [
                    {"url": f"{SYNTHETIC}/service-category", "valueCode": service_category}
                ],
                "adjudication": rows,
            }
        ],
        "total": rows,
    }


def _patient(patient_id: str, name: str) -> dict:
    return {
        "resourceType": "Patient",
        "id": patient_id,
        "name": [{"text": name}],
        "gender": "unknown",
    }


def _org(org_id: str, name: str) -> dict:
    return {"resourceType": "Organization", "id": org_id, "name": name}


def _coverage(coverage_id: str, patient_id: str, insurer_id: str, plan_value: str, plan_name: str) -> dict:
    return {
        "resourceType": "Coverage",
        "id": coverage_id,
        "status": "active",
        "beneficiary": {"reference": f"Patient/{patient_id}"},
        "payor": [{"reference": f"Organization/{insurer_id}"}],
        "class": [
            {
                "type": {"coding": [{"system": COVERAGE_CLASS, "code": "plan"}]},
                "value": plan_value,
                "name": plan_name,
            }
        ],
    }


def _location(loc_id: str, line: str) -> dict:
    return {
        "resourceType": "Location",
        "id": loc_id,
        "address": {"line": [line], "city": "Springfield", "state": "IL", "postalCode": "62701"},
    }


def _role(
    role_id: str,
    practitioner_id: str,
    org_id: str,
    loc_id: str,
    phone: str,
    network: str,
) -> dict:
    return {
        "resourceType": "PractitionerRole",
        "id": role_id,
        "active": True,
        "practitioner": {"reference": f"Practitioner/{practitioner_id}"},
        "organization": {"reference": f"Organization/{org_id}"},
        "location": [{"reference": f"Location/{loc_id}"}],
        "specialty": [
            {
                "coding": [
                    {
                        "system": f"{SYNTHETIC}/specialty",
                        "code": "cardiology",
                        "display": "Cardiology",
                    }
                ]
            }
        ],
        "telecom": [{"system": "phone", "value": phone}],
        "extension": [{"url": f"{SYNTHETIC}/network-status", "valueCode": network}],
    }


def _practitioner(prac_id: str, name: str) -> dict:
    return {"resourceType": "Practitioner", "id": prac_id, "name": [{"text": name}]}


def _bundle(resources: list[dict]) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [{"resource": resource} for resource in resources],
    }


def demo_guide() -> dict:
    return {
        "document_title": "Synthetic 2026 Plan Guide",
        "plan_name": "Synthetic PPO 2026",
        "plan_year": 2026,
        "sections": [
            {
                "id": "4.2",
                "title": "Urgent care",
                "keywords": ["urgent", "care", "copay", "owe", "visit", "deductible", "claim", "latest"],
                "text": (
                    "In-network urgent care has a $75 copay. "
                    "Any deductible amount is the amount recorded on the explanation of benefits. "
                    "The member owes the copay plus that deductible amount."
                ),
                "facts": {
                    "service": "urgent-care",
                    "copay_cents": 7500,
                    "deductible_applies": True,
                },
            },
            {
                "id": "5.1",
                "title": "Physical therapy",
                "keywords": ["physical", "therapy", "visits", "covered", "visit"],
                "text": (
                    "In-network physical therapy is covered. "
                    "The plan allows 20 visits in a calendar year. "
                    "The in-network copay is $30 per visit."
                ),
                "facts": {
                    "service": "physical-therapy",
                    "covered": True,
                    "visit_limit": 20,
                    "service_codes": ["97110"],
                    "copay_cents": 3000,
                },
            },
            {
                "id": "6.1",
                "title": "Specialist care",
                "keywords": ["cardiology", "specialist", "network", "referral", "in-network"],
                "text": (
                    "An in-network specialist visit, including cardiology, has a $50 copay. "
                    "This PPO does not require a referral."
                ),
                "facts": {
                    "service": "specialist",
                    "specialty": "cardiology",
                    "copay_cents": 5000,
                    "referral_required": False,
                    "network": "in-network",
                },
            },
            {
                "id": "7.2",
                "title": "How member cost share is calculated",
                "keywords": ["claim", "partial", "partially", "paid", "coinsurance", "benefit", "latest"],
                "text": (
                    "Outpatient professional services have 20% coinsurance after the deductible. "
                    "The member owes the copay, deductible, and coinsurance amounts on the explanation of benefits. "
                    "The plan paid amount is the benefit adjudication. "
                    "Do not state an amount that is not in this guide or on the explanation of benefits."
                ),
                "facts": {"coinsurance_percent": 20, "applies_after_deductible": True},
            },
            {
                "id": "8.1",
                "title": "Billing review",
                "keywords": ["billing", "review", "approval", "open", "request"],
                "text": (
                    "A member may request a billing review. "
                    "The request stays pending until a human reviewer approves opening it."
                ),
                "facts": {"requires_human_approval": True},
            },
        ],
    }


def other_guide() -> dict:
    return {
        "document_title": "Synthetic 2026 Other Plan Guide",
        "plan_name": "Synthetic HMO 2026",
        "plan_year": 2026,
        "sections": [
            {
                "id": "4.2",
                "title": "Urgent care",
                "keywords": ["urgent", "care", "copay", "owe", "visit"],
                "text": "In-network urgent care has a $40 copay.",
                "facts": {"service": "urgent-care", "copay_cents": 4000, "deductible_applies": False},
            },
            {
                "id": "5.1",
                "title": "Physical therapy",
                "keywords": ["physical", "therapy", "visits", "covered"],
                "text": "In-network physical therapy is covered for 8 visits in a calendar year. The copay is $20.",
                "facts": {
                    "service": "physical-therapy",
                    "covered": True,
                    "visit_limit": 8,
                    "service_codes": ["97110"],
                    "copay_cents": 2000,
                },
            },
            {
                "id": "6.1",
                "title": "Specialist care",
                "keywords": ["cardiology", "specialist", "network", "referral"],
                "text": "An in-network specialist visit has a $35 copay. This HMO requires a referral.",
                "facts": {
                    "service": "specialist",
                    "specialty": "cardiology",
                    "copay_cents": 3500,
                    "referral_required": True,
                    "network": "in-network",
                },
            },
            {
                "id": "7.2",
                "title": "How member cost share is calculated",
                "keywords": ["claim", "partial", "paid", "coinsurance", "latest"],
                "text": "Member amounts come from the explanation of benefits.",
                "facts": {"coinsurance_percent": 20, "applies_after_deductible": True},
            },
            {
                "id": "8.1",
                "title": "Billing review",
                "keywords": ["billing", "review", "approval"],
                "text": "A billing review stays pending until a human reviewer approves opening it.",
                "facts": {"requires_human_approval": True},
            },
        ],
    }


def _pt(eob_id: str, when: str, patient: str, coverage: str) -> dict:
    return _eob(
        eob_id,
        patient,
        coverage,
        "clinic-pt",
        "synthetic-plan",
        when,
        when,
        "97110",
        "Physical therapy visit",
        "physical-therapy",
        {"submitted": 120, "eligible": 90, "benefit": 60, "copay": 30, "deductible": 0, "coinsurance": 0},
    )


def demo_bundle() -> dict:
    patient = "patient-mbr-1001"
    coverage = "cov-mbr-1001"
    resources: list[dict] = [
        _patient(patient, "Alex Rivera"),
        _org("synthetic-plan", "Synthetic PPO 2026"),
        _org("clinic-urgent", "Demo Urgent Care"),
        _org("clinic-office", "Demo Office"),
        _org("clinic-pt", "Demo Physical Therapy"),
        _org("clinic-northwind", "Northwind Heart Clinic"),
        _org("clinic-lakeview", "Lakeview Cardiology"),
        _org("clinic-harbor", "Harbor Specialty Heart"),
        _coverage(coverage, patient, "synthetic-plan", "SYN-PPO-2026", "Synthetic PPO 2026"),
        _eob(
            "DEMO-1048",
            patient,
            coverage,
            "clinic-urgent",
            "synthetic-plan",
            "2026-03-02",
            "2026-03-04",
            "99213",
            "Urgent care visit",
            "urgent-care",
            {"submitted": 250, "eligible": 180, "benefit": 95, "copay": 75, "deductible": 10, "coinsurance": 0},
        ),
        _eob(
            "DEMO-2201",
            patient,
            coverage,
            "clinic-office",
            "synthetic-plan",
            "2026-02-10",
            "2026-02-12",
            "99214",
            "Office visit",
            "outpatient-professional",
            {"submitted": 400, "eligible": 250, "benefit": 160, "copay": 0, "deductible": 50, "coinsurance": 40},
        ),
        _pt("DEMO-PT-01", "2026-01-06", patient, coverage),
        _pt("DEMO-PT-02", "2026-01-13", patient, coverage),
        _pt("DEMO-PT-03", "2026-01-20", patient, coverage),
        _pt("DEMO-PT-04", "2026-01-27", patient, coverage),
        _pt("DEMO-PT-OLD", "2025-11-01", patient, coverage),
        _practitioner("prac-patel", "Dr. Sam Patel"),
        _practitioner("prac-chen", "Dr. Riley Chen"),
        _practitioner("prac-blake", "Dr. Morgan Blake"),
        _location("loc-northwind", "100 Demo Heart Ave"),
        _location("loc-lakeview", "200 Sample Street"),
        _location("loc-harbor", "900 Outside Network Rd"),
        _role("role-patel", "prac-patel", "clinic-northwind", "loc-northwind", "555-0141", "in-network"),
        _role("role-chen", "prac-chen", "clinic-lakeview", "loc-lakeview", "555-0142", "in-network"),
        _role("role-blake", "prac-blake", "clinic-harbor", "loc-harbor", "555-0199", "out-of-network"),
    ]
    return _bundle(resources)


def other_bundle() -> dict:
    patient = "patient-mbr-2001"
    coverage = "cov-mbr-2001"
    resources = [
        _patient(patient, "Jordan Lee"),
        _org("other-plan", "Synthetic HMO 2026"),
        _org("clinic-quinn", "Quinn Cardiology"),
        _coverage(coverage, patient, "other-plan", "SYN-HMO-2026", "Synthetic HMO 2026"),
        _eob(
            "OTHER-9001",
            patient,
            coverage,
            "clinic-quinn",
            "other-plan",
            "2026-03-01",
            "2026-03-03",
            "99213",
            "Urgent care visit",
            "urgent-care",
            {"submitted": 100, "eligible": 100, "benefit": 60, "copay": 40, "deductible": 0, "coinsurance": 0},
        ),
        _practitioner("prac-quinn", "Dr. Casey Quinn"),
        _location("loc-quinn", "15 Other Plan Way"),
        _role("role-quinn", "prac-quinn", "clinic-quinn", "loc-quinn", "555-0177", "in-network"),
    ]
    return _bundle(resources)


def actors() -> dict:
    return {
        "demo-member": {
            "tenant_id": "demo-plan",
            "role": "member",
            "subject_id": "MBR-1001",
            "patient_id": "patient-mbr-1001",
            "display_name": "Alex Rivera",
        },
        "demo-reviewer": {
            "tenant_id": "demo-plan",
            "role": "reviewer",
            "subject_id": "REV-1",
            "patient_id": None,
            "display_name": "Synthetic Reviewer",
        },
        "other-member": {
            "tenant_id": "other-plan",
            "role": "member",
            "subject_id": "MBR-2001",
            "patient_id": "patient-mbr-2001",
            "display_name": "Jordan Lee",
        },
    }


def write_all(root: Path | None = None) -> Path:
    target = root or DATA_DIR
    files = {
        target / "actors.json": actors(),
        target / "demo-plan" / "guide.json": demo_guide(),
        target / "demo-plan" / "bundle.json": demo_bundle(),
        target / "other-plan" / "guide.json": other_guide(),
        target / "other-plan" / "bundle.json": other_bundle(),
    }
    for path, payload in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> None:
    print(write_all())


if __name__ == "__main__":
    main()
