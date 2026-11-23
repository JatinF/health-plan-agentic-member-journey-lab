"""Versioned member reads. Amounts come from the synthetic explanation of benefits."""

from tests.conftest import auth
from membercare.contracts import cents_from_usd_string


def test_member_profile_and_coverage(client) -> None:
    denied = client.get("/api/v1/me")
    assert denied.status_code == 401

    reviewer = client.get("/api/v1/me", headers=auth("demo-reviewer"))
    assert reviewer.status_code == 403
    assert reviewer.json()["detail"]["error"] == "permission_denied"

    profile = client.get("/api/v1/me", headers=auth("demo-member")).json()
    assert profile["tool"] == "get_member_profile"
    assert profile["schema_version"] == "1.0"
    assert profile["data"]["display_name"] == "Alex Rivera"
    assert profile["data"]["member_id"] == "MBR-1001"
    assert profile["source"]["resource_type"] == "Patient"

    active = client.get("/api/v1/me/coverage?service_date=2026-03-02", headers=auth("demo-member")).json()
    assert active["data"]["evidence"] == "active"
    assert active["data"]["coverage"]["id"] == "cov-mbr-1001"
    assert active["source"]["resource_type"] == "Coverage"

    expired = client.get("/api/v1/me/coverage?service_date=2025-11-01", headers=auth("demo-member")).json()
    assert expired["data"]["evidence"] == "plan_year_mismatch"
    assert expired["data"]["coverage"] is None
    assert expired["source"]["resource_type"] == "PlanGuide"


def test_eob_amounts_are_reconciled_and_isolated(client) -> None:
    own = client.get("/api/v1/me/eobs/DEMO-1048", headers=auth("demo-member"))
    assert own.status_code == 200
    body = own.json()
    data = body["data"]
    assert body["source"] == {"resource_type": "ExplanationOfBenefit", "resource_id": "DEMO-1048"}
    assert data["claim_status"] == "complete"
    assert data["currency"] == "USD"
    assert data["provider_charge"] == "250.00"
    assert data["allowed_amount"] == "180.00"
    assert data["plan_paid"] == "95.00"
    assert data["member_responsibility"] == "85.00"
    assert data["copay"] == "75.00"
    assert data["deductible"] == "10.00"
    assert data["coinsurance"] == "0.00"
    member = cents_from_usd_string(data["member_responsibility"])
    parts = sum(cents_from_usd_string(data[name]) for name in ("copay", "deductible", "coinsurance"))
    assert member == parts == 8500
    assert cents_from_usd_string(data["plan_paid"]) + member == cents_from_usd_string(data["allowed_amount"])

    hidden = client.get("/api/v1/me/eobs/DEMO-1048", headers=auth("other-member"))
    assert hidden.status_code == 404
    assert hidden.json()["detail"]["error"] == "not_found"

    missing = client.get("/api/v1/me/eobs/DEMO-9999", headers=auth("demo-member"))
    assert missing.status_code == 404

    page = client.get("/api/v1/me/eobs?limit=1", headers=auth("demo-member")).json()["data"]
    assert len(page["eobs"]) == 1
    assert page["next_cursor"] == page["eobs"][0]["eob_id"]
    bad_cursor = client.get("/api/v1/me/eobs?cursor=OTHER-9001", headers=auth("demo-member"))
    assert bad_cursor.status_code == 400


def test_assistant_run_is_scoped_to_the_actor(client) -> None:
    started = client.post(
        "/api/v1/assistant/runs",
        headers=auth("demo-member"),
        json={"question": "Is physical therapy covered, and how many visits?"},
    )
    assert started.status_code == 200
    body = started.json()
    assert body["id"] == body["thread_id"]
    assert "16 remain" in body["answer"]

    saved = client.get(f"/api/v1/assistant/runs/{body['id']}", headers=auth("demo-member"))
    assert saved.status_code == 200
    assert "16 remain" in saved.json()["run"]["answer"]
    assert "question" not in saved.json()["run"]

    other = client.get(f"/api/v1/assistant/runs/{body['id']}", headers=auth("other-member"))
    assert other.status_code == 404

    transcript = client.post(
        "/api/v1/voice/transcribe",
        headers=auth("demo-member"),
        json={"transcript": "What is the meaning of the deductible moon?"},
    )
    assert transcript.status_code == 200
    spoken = transcript.json()
    assert spoken["server_speech_recognizer"] == "not_used"
    assert "$" not in spoken["answer"]

    missing_case = client.post(
        "/api/v1/approvals/CASE-9999/decision",
        headers=auth("demo-reviewer"),
        json={"decision": "approve"},
    )
    assert missing_case.status_code == 404
    listed = client.get("/api/v1/cases", headers=auth("demo-member"))
    assert listed.status_code == 200
    assert "cases" in listed.json()
