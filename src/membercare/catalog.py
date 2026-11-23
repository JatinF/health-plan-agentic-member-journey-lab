"""Load synthetic tenants. Every reference used by the lab must resolve inside the tenant."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from membercare.errors import LabError
from membercare.money import explanation_amounts

REFERENCE_FIELDS = ("patient", "insurer", "provider", "beneficiary")


@dataclass(frozen=True)
class Actor:
    token: str
    tenant_id: str
    role: str
    subject_id: str
    patient_id: str | None
    display_name: str


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    guide: dict
    resources: dict[tuple[str, str], dict]

    def get(self, resource_type: str, resource_id: str) -> dict:
        try:
            return self.resources[(resource_type, resource_id)]
        except KeyError as exc:
            raise LabError("not_found", f"{resource_type}/{resource_id} was not found") from exc

    def of_type(self, resource_type: str) -> list[dict]:
        return [resource for (kind, _), resource in self.resources.items() if kind == resource_type]

    def section(self, section_id: str) -> dict:
        for section in self.guide["sections"]:
            if section["id"] == section_id:
                found = dict(section)
                found["document_title"] = self.guide["document_title"]
                found["plan_name"] = self.guide["plan_name"]
                found["plan_year"] = self.guide["plan_year"]
                return found
        raise LabError("not_found", f"plan section {section_id} was not found")


class Catalog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.actors = _load_actors(root / "actors.json")
        self.tenants = {
            "demo-plan": _load_tenant(root / "demo-plan", "demo-plan"),
            "other-plan": _load_tenant(root / "other-plan", "other-plan"),
        }
        for tenant in self.tenants.values():
            _validate_tenant(tenant)

    def actor(self, token: str) -> Actor | None:
        return self.actors.get(token)

    def require_actor(self, token: str) -> Actor:
        actor = self.actor(token)
        if actor is None:
            raise LabError("permission_denied", "unknown lab actor")
        return actor

    def tenant_for(self, actor: Actor) -> Tenant:
        try:
            return self.tenants[actor.tenant_id]
        except KeyError as exc:
            raise LabError("permission_denied", "actor tenant is not loaded") from exc


def default_data_dir() -> Path:
    return Path(__file__).resolve().parent / "data"


def load_catalog(root: Path | None = None) -> Catalog:
    return Catalog(root or default_data_dir())


def _load_actors(path: Path) -> dict[str, Actor]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    actors = {}
    for token, row in raw.items():
        actors[token] = Actor(
            token=token,
            tenant_id=row["tenant_id"],
            role=row["role"],
            subject_id=row["subject_id"],
            patient_id=row["patient_id"],
            display_name=row["display_name"],
        )
    return actors


def _load_tenant(directory: Path, tenant_id: str) -> Tenant:
    guide = json.loads((directory / "guide.json").read_text(encoding="utf-8"))
    bundle = json.loads((directory / "bundle.json").read_text(encoding="utf-8"))
    resources: dict[tuple[str, str], dict] = {}
    for entry in bundle["entry"]:
        resource = entry["resource"]
        key = (resource["resourceType"], resource["id"])
        if key in resources:
            raise LabError("inconsistent", f"duplicate {key[0]}/{key[1]}")
        resources[key] = resource
    return Tenant(tenant_id=tenant_id, guide=guide, resources=resources)


def _validate_tenant(tenant: Tenant) -> None:
    for (kind, resource_id), resource in tenant.resources.items():
        if kind == "ExplanationOfBenefit":
            explanation_amounts(resource)
            _require_reference(tenant, resource["patient"]["reference"])
            _require_reference(tenant, resource["insurance"][0]["coverage"]["reference"])
        if kind == "Coverage":
            _require_reference(tenant, resource["beneficiary"]["reference"])
            if resource["status"] != "active":
                raise LabError("inconsistent", f"coverage {resource_id} is not active")
        if kind == "PractitionerRole":
            _require_reference(tenant, resource["practitioner"]["reference"])
            _require_reference(tenant, resource["organization"]["reference"])
            _require_reference(tenant, resource["location"][0]["reference"])
    for section in tenant.guide["sections"]:
        facts = section.get("facts") or {}
        if "copay_cents" in facts:
            dollars = facts["copay_cents"] // 100
            if f"${dollars}" not in section["text"]:
                raise LabError("inconsistent", f"section {section['id']} text omits its copay")


def _require_reference(tenant: Tenant, reference: str) -> None:
    resource_type, _, resource_id = reference.partition("/")
    if (resource_type, resource_id) not in tenant.resources:
        raise LabError("inconsistent", f"dangling reference {reference}")
