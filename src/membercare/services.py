"""Tool implementations shared by the MCP servers. The graph reaches these only through MCP."""

from __future__ import annotations

from membercare.catalog import Actor, Catalog
from membercare.cases import CaseStore
from membercare.contracts import service_year, usd_string
from membercare.errors import LabError
from membercare.money import explanation_amounts
from membercare.observe import Metrics
from membercare.retrieve import search_sections

SERVICE_CATEGORY = "https://synthetic.example/service-category"
NETWORK_STATUS = "https://synthetic.example/network-status"


class Services:
    def __init__(self, catalog: Catalog, cases: CaseStore, metrics: Metrics) -> None:
        self.catalog = catalog
        self.cases = cases
        self.metrics = metrics

    def actor(self, token: str) -> Actor:
        actor = self.catalog.require_actor(token)
        return actor

    def search_plan_sections(self, actor_token: str, query: str, limit: int = 3) -> dict:
        actor = self._member_or_reviewer(actor_token)
        tenant = self.catalog.tenant_for(actor)
        found = search_sections(tenant.guide, query, limit)
        return {"sections": [_public_section(section) for section in found]}

    def get_plan_section(self, actor_token: str, section_id: str) -> dict:
        actor = self._member_or_reviewer(actor_token)
        tenant = self.catalog.tenant_for(actor)
        return {"section": _public_section(tenant.section(section_id))}

    def get_coverage(self, actor_token: str) -> dict:
        actor = self._member(actor_token)
        tenant = self.catalog.tenant_for(actor)
        matches = []
        for resource in tenant.of_type("Coverage"):
            beneficiary = resource["beneficiary"]["reference"].split("/", 1)[1]
            if beneficiary == actor.patient_id:
                matches.append(resource)
        if len(matches) != 1:
            raise LabError("inconsistent", "member does not have exactly one coverage record")
        coverage = matches[0]
        plan = coverage["class"][0]
        return {
            "coverage": {
                "id": coverage["id"],
                "status": coverage["status"],
                "patient_id": actor.patient_id,
                "plan_value": plan["value"],
                "plan_name": plan["name"],
            }
        }

    def list_explanations(self, actor_token: str) -> dict:
        actor = self._member(actor_token)
        return {"explanations": [self._summary(actor, resource) for resource in self._own_eobs(actor)]}

    def get_explanation(self, actor_token: str, eob_id: str) -> dict:
        actor = self._member(actor_token)
        tenant = self.catalog.tenant_for(actor)
        try:
            resource = tenant.get("ExplanationOfBenefit", eob_id)
        except LabError:
            self.metrics.inc("membercare_permission_denied_total", {"result": "not_found"})
            self.cases.audit(actor, "get_explanation", "not_found", eob_id)
            raise LabError("not_found", "explanation of benefit was not found") from None
        patient_id = resource["patient"]["reference"].split("/", 1)[1]
        if patient_id != actor.patient_id:
            self.metrics.inc("membercare_permission_denied_total", {"result": "hidden"})
            self.cases.audit(actor, "get_explanation", "not_found", eob_id)
            raise LabError("not_found", "explanation of benefit was not found")
        return {"explanation": self._summary(actor, resource)}

    def search_providers(
        self,
        actor_token: str,
        specialty: str,
        network_status: str,
        location: str = "",
    ) -> dict:
        actor = self._member_or_reviewer(actor_token)
        tenant = self.catalog.tenant_for(actor)
        found = []
        for role in tenant.of_type("PractitionerRole"):
            role_specialty = role["specialty"][0]["coding"][0]["code"]
            network = _extension(role, NETWORK_STATUS)
            if role_specialty != specialty or network != network_status:
                continue
            row = self._provider_row(tenant, role)
            if location and location.casefold() not in row["city"].casefold():
                continue
            found.append(row)
        found.sort(key=lambda row: row["organization"])
        return {"providers": found}

    def member_profile(self, actor_token: str) -> tuple[dict, dict]:
        actor = self._member(actor_token)
        tenant = self.catalog.tenant_for(actor)
        patient = tenant.get("Patient", actor.patient_id or "")
        data = {
            "member_id": actor.subject_id,
            "display_name": patient["name"][0]["text"],
            "patient_id": actor.patient_id,
            "tenant_id": actor.tenant_id,
            "plan_name": tenant.guide["plan_name"],
            "plan_year": tenant.guide["plan_year"],
        }
        return data, {"resource_type": "Patient", "resource_id": actor.patient_id}

    def active_coverage(self, actor_token: str, service_date: str) -> tuple[dict, dict]:
        actor = self._member(actor_token)
        tenant = self.catalog.tenant_for(actor)
        year = service_year(service_date)
        coverage = self.get_coverage(actor_token)["coverage"]
        if year != tenant.guide["plan_year"]:
            return (
                {
                    "evidence": "plan_year_mismatch",
                    "service_date": service_date,
                    "plan_year": tenant.guide["plan_year"],
                    "coverage": None,
                },
                {
                    "resource_type": "PlanGuide",
                    "resource_id": tenant.guide["document_title"],
                    "plan_year": tenant.guide["plan_year"],
                },
            )
        return (
            {
                "evidence": "active",
                "service_date": service_date,
                "plan_year": year,
                "coverage": coverage,
            },
            {"resource_type": "Coverage", "resource_id": coverage["id"]},
        )

    def benefit_details(self, actor_token: str, service_code: str, service_date: str) -> tuple[dict, dict]:
        actor = self._member(actor_token)
        tenant = self.catalog.tenant_for(actor)
        year = service_year(service_date)
        source = {
            "resource_type": "PlanGuide",
            "resource_id": tenant.guide["document_title"],
            "plan_year": tenant.guide["plan_year"],
        }
        if year != tenant.guide["plan_year"]:
            return (
                {
                    "evidence": "insufficient",
                    "reason": "service date is outside the loaded plan year",
                    "service_code": service_code,
                    "service_date": service_date,
                    "plan_year": tenant.guide["plan_year"],
                    "informational": True,
                    "binding_determination": False,
                    "section": None,
                },
                source,
            )
        match = None
        for section in tenant.guide["sections"]:
            codes = (section.get("facts") or {}).get("service_codes") or []
            if service_code in codes:
                match = tenant.section(section["id"])
                break
        if match is None:
            return (
                {
                    "evidence": "insufficient",
                    "reason": "no applicable policy section for that service code",
                    "service_code": service_code,
                    "service_date": service_date,
                    "plan_year": tenant.guide["plan_year"],
                    "informational": True,
                    "binding_determination": False,
                    "section": None,
                },
                source,
            )
        return (
            {
                "evidence": "found",
                "service_code": service_code,
                "service_date": service_date,
                "plan_year": tenant.guide["plan_year"],
                "informational": True,
                "binding_determination": False,
                "section": _public_section(match),
            },
            {"resource_type": "PlanGuide", "resource_id": match["id"], "plan_year": tenant.guide["plan_year"]},
        )

    def list_member_eobs(self, actor_token: str, limit: int = 20, cursor: str | None = None) -> tuple[dict, dict]:
        actor = self._member(actor_token)
        rows = [self._contract_eob(actor, resource) for resource in self._own_eobs(actor)]
        rows.sort(key=lambda row: (row["service_date"], row["eob_id"]), reverse=True)
        start = 0
        if cursor:
            ids = [row["eob_id"] for row in rows]
            if cursor not in ids:
                raise LabError("invalid", "cursor was not found")
            start = ids.index(cursor) + 1
        page = rows[start : start + limit]
        next_cursor = page[-1]["eob_id"] if page and start + limit < len(rows) else None
        return (
            {"eobs": page, "next_cursor": next_cursor},
            {"resource_type": "ExplanationOfBenefit", "resource_id": "list"},
        )

    def eob_details(self, actor_token: str, eob_id: str) -> tuple[dict, dict]:
        actor = self._member(actor_token)
        self.get_explanation(actor_token, eob_id)
        resource = self.catalog.tenant_for(actor).get("ExplanationOfBenefit", eob_id)
        return (
            self._contract_eob(actor, resource),
            {"resource_type": "ExplanationOfBenefit", "resource_id": eob_id},
        )

    def search_policy_documents(self, actor_token: str, query: str, effective_date: str) -> tuple[dict, dict]:
        actor = self._member_or_reviewer(actor_token)
        tenant = self.catalog.tenant_for(actor)
        year = service_year(effective_date)
        source = {
            "resource_type": "PlanGuide",
            "resource_id": tenant.guide["document_title"],
            "plan_year": tenant.guide["plan_year"],
        }
        if year != tenant.guide["plan_year"]:
            return (
                {
                    "evidence": "insufficient",
                    "reason": "effective date is outside the loaded plan year",
                    "sections": [],
                    "plan_year": tenant.guide["plan_year"],
                    "effective_date": effective_date,
                },
                source,
            )
        found = [_public_section(section) for section in search_sections(tenant.guide, query, 5)]
        return (
            {
                "evidence": "found" if found else "insufficient",
                "reason": "" if found else "no applicable policy section was retrieved",
                "sections": found,
                "plan_year": tenant.guide["plan_year"],
                "effective_date": effective_date,
            },
            source,
        )

    def provider_details(self, actor_token: str, provider_id: str) -> tuple[dict, dict]:
        actor = self._member_or_reviewer(actor_token)
        tenant = self.catalog.tenant_for(actor)
        try:
            role = tenant.get("PractitionerRole", provider_id)
        except LabError:
            self.metrics.inc("membercare_permission_denied_total", {"result": "not_found"})
            self.cases.audit(actor, "get_provider_details", "not_found", provider_id)
            raise LabError("not_found", "provider was not found") from None
        return (
            self._provider_row(tenant, role),
            {"resource_type": "PractitionerRole", "resource_id": provider_id},
        )

    def draft_billing_review(self, actor_token: str, eob_id: str, reason: str) -> tuple[dict, dict]:
        actor = self._member(actor_token)
        explanation = self.get_explanation(actor_token, eob_id)["explanation"]
        self.cases.audit(actor, "draft_billing_review", "drafted", eob_id)
        data = {
            "eob_id": eob_id,
            "reason": reason.strip() or "Member requested a billing review",
            "status": "draft",
            "currency": "USD",
            "member_responsibility": usd_string(explanation["amounts"]["member_owes"]),
            "requires_approval": True,
        }
        return data, {"resource_type": "ExplanationOfBenefit", "resource_id": eob_id}

    def submit_billing_review(self, actor_token: str, case_id: str, idempotency_key: str) -> tuple[dict, dict]:
        actor = self.catalog.require_actor(actor_token)
        if actor.role != "reviewer":
            self.metrics.inc("membercare_permission_denied_total", {"result": "submit"})
            self.cases.audit(actor, "submit_billing_review", "permission_denied", case_id)
            raise LabError("permission_denied", "a reviewer actor is required")
        if not idempotency_key.strip():
            raise LabError("invalid", "idempotency key is required")
        case = self.cases.get(actor, case_id)
        if case["status"] == "pending_approval":
            self.cases.audit(actor, "submit_billing_review", "approval_required", case_id)
            raise LabError("approval_required", "a reviewer must approve the case before it opens")
        if case["status"] == "approved":
            case = self.cases.open_case(actor, case_id)
            self.metrics.inc("membercare_approval_total", {"result": "opened"})
        elif case["status"] != "open":
            raise LabError("invalid", f"cannot submit a case that is {case['status']}")
        self.cases.audit(actor, "submit_billing_review", case["status"], case_id)
        return (
            {"case_id": case["id"], "status": case["status"], "eob_id": case["eob_id"]},
            {"resource_type": "MemberCase", "resource_id": case["id"]},
        )

    def case_status(self, actor_token: str, case_id: str) -> tuple[dict, dict]:
        case = self.get_case(actor_token, case_id)["case"]
        return (
            {"case_id": case["id"], "status": case["status"], "eob_id": case["eob_id"]},
            {"resource_type": "MemberCase", "resource_id": case["id"]},
        )

    def request_billing_review(self, actor_token: str, eob_id: str, reason: str, thread_id: str) -> dict:
        actor = self._member(actor_token)
        self.get_explanation(actor_token, eob_id)
        case = self.cases.request(actor, eob_id, reason or "Member requested a billing review", thread_id)
        self.metrics.inc("membercare_approval_total", {"result": "requested"})
        return {"case": _public_case(case)}

    def open_billing_review(self, actor_token: str, case_id: str) -> dict:
        actor = self.catalog.require_actor(actor_token)
        if actor.role != "reviewer":
            self.metrics.inc("membercare_permission_denied_total", {"result": "open"})
            self.cases.audit(actor, "open_billing_review", "permission_denied", case_id)
            raise LabError("permission_denied", "a reviewer actor is required")
        case = self.cases.open_case(actor, case_id)
        self.metrics.inc("membercare_approval_total", {"result": "opened"})
        return {"case": _public_case(case)}

    def reject_billing_review(self, actor_token: str, case_id: str) -> dict:
        actor = self.catalog.require_actor(actor_token)
        if actor.role != "reviewer":
            self.metrics.inc("membercare_permission_denied_total", {"result": "reject"})
            self.cases.audit(actor, "reject_billing_review", "permission_denied", case_id)
            raise LabError("permission_denied", "a reviewer actor is required")
        case = self.cases.reject(actor, case_id)
        self.metrics.inc("membercare_approval_total", {"result": "rejected"})
        return {"case": _public_case(case)}

    def approve_billing_review(self, actor_token: str, case_id: str) -> dict:
        actor = self.catalog.require_actor(actor_token)
        if actor.role != "reviewer":
            self.metrics.inc("membercare_permission_denied_total", {"result": "approve"})
            self.cases.audit(actor, "approve_billing_review", "permission_denied", case_id)
            raise LabError("permission_denied", "a reviewer actor is required")
        case = self.cases.approve(actor, case_id)
        self.metrics.inc("membercare_approval_total", {"result": "approved"})
        return {"case": _public_case(case)}

    def get_case(self, actor_token: str, case_id: str) -> dict:
        actor = self._member_or_reviewer(actor_token)
        return {"case": _public_case(self.cases.get(actor, case_id))}

    def _own_eobs(self, actor: Actor) -> list[dict]:
        tenant = self.catalog.tenant_for(actor)
        owned = []
        for resource in tenant.of_type("ExplanationOfBenefit"):
            patient_id = resource["patient"]["reference"].split("/", 1)[1]
            if patient_id == actor.patient_id:
                owned.append(resource)
        return owned

    def _provider_row(self, tenant, role: dict) -> dict:
        practitioner = tenant.get("Practitioner", role["practitioner"]["reference"].split("/", 1)[1])
        organization = tenant.get("Organization", role["organization"]["reference"].split("/", 1)[1])
        location = tenant.get("Location", role["location"][0]["reference"].split("/", 1)[1])
        return {
            "role_id": role["id"],
            "practitioner": practitioner["name"][0]["text"],
            "organization": organization["name"],
            "line": location["address"]["line"][0],
            "city": location["address"]["city"],
            "state": location["address"]["state"],
            "phone": role["telecom"][0]["value"],
            "network_status": _extension(role, NETWORK_STATUS),
            "specialty": role["specialty"][0]["coding"][0]["code"],
        }

    def _contract_eob(self, actor: Actor, resource: dict) -> dict:
        summary = self._summary(actor, resource)
        amounts = summary["amounts"]
        return {
            "eob_id": summary["id"],
            "claim_status": resource.get("outcome") or "",
            "currency": "USD",
            "provider_charge": usd_string(amounts["submitted"]),
            "allowed_amount": usd_string(amounts["eligible"]),
            "plan_paid": usd_string(amounts["benefit"]),
            "member_responsibility": usd_string(amounts["member_owes"]),
            "copay": usd_string(amounts["copay"]),
            "deductible": usd_string(amounts["deductible"]),
            "coinsurance": usd_string(amounts["coinsurance"]),
            "service_date": summary["billable_end"],
            "service_code": summary["service_code"],
            "service_category": summary["service_category"],
        }

    def _summary(self, actor: Actor, resource: dict) -> dict:
        try:
            amounts = explanation_amounts(resource)
        except LabError:
            self.metrics.inc("membercare_eob_inconsistent_total", {"result": "inconsistent"})
            raise
        item = resource["item"][0]
        return {
            "id": resource["id"],
            "patient_id": actor.patient_id,
            "service_category": _extension(item, SERVICE_CATEGORY),
            "service_code": item["productOrService"]["coding"][0]["code"],
            "service_display": item["productOrService"]["coding"][0]["display"],
            "billable_end": resource["billablePeriod"]["end"],
            "coverage_id": resource["insurance"][0]["coverage"]["reference"].split("/", 1)[1],
            "amounts": amounts,
        }

    def _member(self, token: str) -> Actor:
        actor = self.catalog.require_actor(token)
        if actor.role != "member" or not actor.patient_id:
            self.metrics.inc("membercare_permission_denied_total", {"result": "role"})
            self.cases.audit(actor, "member_tool", "permission_denied", actor.role)
            raise LabError("permission_denied", "a member actor is required")
        return actor

    def _member_or_reviewer(self, token: str) -> Actor:
        actor = self.catalog.require_actor(token)
        if actor.role not in {"member", "reviewer"}:
            raise LabError("permission_denied", "actor role is not allowed")
        return actor


def _extension(resource: dict, url: str) -> str:
    for row in resource.get("extension") or []:
        if row.get("url") == url:
            return row.get("valueCode", "")
    raise LabError("inconsistent", f"missing extension {url}")


def _public_section(section: dict) -> dict:
    return {
        "id": section["id"],
        "title": section["title"],
        "text": section["text"],
        "facts": section["facts"],
        "document_title": section["document_title"],
        "plan_name": section["plan_name"],
        "plan_year": section["plan_year"],
        "score": section.get("score", 0),
    }


def _public_case(case: dict) -> dict:
    return {
        "id": case["id"],
        "tenant_id": case["tenant_id"],
        "member_id": case["member_id"],
        "eob_id": case["eob_id"],
        "reason": case["reason"],
        "thread_id": case["thread_id"],
        "status": case["status"],
        "created_at": case["created_at"],
    }
