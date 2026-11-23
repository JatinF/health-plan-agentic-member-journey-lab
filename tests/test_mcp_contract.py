"""Blueprint MCP tool names return the shared envelope and do not invent amounts."""

import asyncio
from pathlib import Path


def test_contract_tools_isolate_members_and_skip_unapproved_writes(tmp_path: Path) -> None:
    asyncio.run(_contract(tmp_path))


async def _contract(tmp_path: Path) -> None:
    from mcp import Client

    from membercare.cases import CaseStore
    from membercare.catalog import default_data_dir, load_catalog
    from membercare.config import Settings
    from membercare.mcp.servers import build_servers
    from membercare.observe import Metrics
    from membercare.services import Services

    settings = Settings(
        data_dir=default_data_dir(),
        db_path=tmp_path / "lab.db",
        checkpoint_path=tmp_path / "checkpoints.sqlite",
        web_dir=tmp_path,
    )
    catalog = load_catalog(settings.data_dir)
    store = CaseStore(settings.db_path)
    services = Services(catalog, store, Metrics())
    servers = build_servers(services)
    try:
        async with Client(servers["member_data"]) as client:
            details = _body(
                await client.call_tool(
                    "get_eob_details",
                    {"actor_token": "demo-member", "eob_id": "DEMO-1048"},
                )
            )
            hidden = _body(
                await client.call_tool(
                    "get_eob_details",
                    {"actor_token": "other-member", "eob_id": "DEMO-1048"},
                )
            )
            old_benefit = _body(
                await client.call_tool(
                    "get_benefit_details",
                    {"actor_token": "demo-member", "service_code": "97110", "service_date": "2025-11-01"},
                )
            )
            current_benefit = _body(
                await client.call_tool(
                    "get_benefit_details",
                    {"actor_token": "demo-member", "service_code": "97110", "service_date": "2026-03-02"},
                )
            )
        async with Client(servers["knowledge"]) as client:
            stale = _body(
                await client.call_tool(
                    "search_policy_documents",
                    {
                        "actor_token": "demo-member",
                        "query": "urgent care copay",
                        "effective_date": "2025-06-01",
                    },
                )
            )
            provider = _body(
                await client.call_tool(
                    "get_provider_details",
                    {"actor_token": "demo-member", "provider_id": "role-patel"},
                )
            )
            foreign = _body(
                await client.call_tool(
                    "get_provider_details",
                    {"actor_token": "demo-member", "provider_id": "role-quinn"},
                )
            )
        async with Client(servers["member_actions"]) as client:
            draft = _body(
                await client.call_tool(
                    "draft_billing_review",
                    {"actor_token": "demo-member", "eob_id": "DEMO-1048", "reason": "copay question"},
                )
            )
            assert store.list_cases(catalog.require_actor("demo-member")) == []
            created = services.request_billing_review("demo-member", "DEMO-1048", "copay question", "thread-contract")
            case_id = created["case"]["id"]
            blocked = _body(
                await client.call_tool(
                    "submit_billing_review",
                    {"actor_token": "demo-member", "case_id": case_id, "idempotency_key": "replay-1"},
                )
            )
            waiting = _body(
                await client.call_tool(
                    "submit_billing_review",
                    {"actor_token": "demo-reviewer", "case_id": case_id, "idempotency_key": "replay-1"},
                )
            )
            services.approve_billing_review("demo-reviewer", case_id)
            opened = _body(
                await client.call_tool(
                    "submit_billing_review",
                    {"actor_token": "demo-reviewer", "case_id": case_id, "idempotency_key": "replay-1"},
                )
            )
            replay = _body(
                await client.call_tool(
                    "submit_billing_review",
                    {"actor_token": "demo-reviewer", "case_id": case_id, "idempotency_key": "replay-1"},
                )
            )
    finally:
        store.close()

    assert details["status"] == "success"
    assert details["tool"] == "get_eob_details"
    assert details["schema_version"] == "1.0"
    assert details["data"]["member_responsibility"] == "85.00"
    assert details["data"]["provider_charge"] == "250.00"
    assert hidden["status"] == "error"
    assert hidden["error"] == "not_found"
    assert old_benefit["data"]["evidence"] == "insufficient"
    assert old_benefit["data"]["section"] is None
    assert current_benefit["data"]["evidence"] == "found"
    assert current_benefit["data"]["binding_determination"] is False
    assert current_benefit["data"]["section"]["facts"]["visit_limit"] == 20
    assert stale["data"]["evidence"] == "insufficient"
    assert stale["data"]["sections"] == []
    assert provider["data"]["network_status"] == "in-network"
    assert "Patel" in provider["data"]["practitioner"]
    assert foreign["error"] == "not_found"
    assert draft["data"]["status"] == "draft"
    assert "case_id" not in draft["data"]
    assert blocked["error"] == "permission_denied"
    assert waiting["error"] == "approval_required"
    assert opened["data"]["case_id"] == replay["data"]["case_id"] == case_id
    assert opened["data"]["status"] == replay["data"]["status"] == "open"


def _body(result) -> dict:
    assert result.is_error is False
    payload = result.structured_content or {}
    if isinstance(payload, dict) and set(payload.keys()) == {"result"} and isinstance(payload["result"], dict):
        payload = payload["result"]
    return payload
