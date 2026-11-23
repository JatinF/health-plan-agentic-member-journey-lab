"""Fail-closed scorecard for the five member journeys. There is no fuzzy score."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from membercare.api import create_app
from membercare.catalog import default_data_dir
from membercare.config import Settings, repo_root


CASES = [
    {
        "name": "benefits",
        "token": "demo-member",
        "path": "/api/chat",
        "payload": {"question": "Is physical therapy covered, and how many visits?"},
        "contains": ["20 visits", "16 remain", "$30", "§5.1"],
        "absent": ["HMO", "Quinn", "DEMO-PT-OLD"],
    },
    {
        "name": "claims",
        "token": "demo-member",
        "path": "/api/chat",
        "payload": {"question": "Why do I owe $85 for my urgent care visit?"},
        "contains": ["$75", "$10", "§4.2", "DEMO-1048"],
        "absent": ["OTHER-9001", "Quinn"],
        "member_owes_cents": 8500,
    },
    {
        "name": "care",
        "token": "demo-member",
        "path": "/api/chat",
        "payload": {"question": "Find in-network cardiology options."},
        "contains": ["Dr. Sam Patel", "Dr. Riley Chen", "$50", "§6.1"],
        "absent": ["Harbor", "Quinn"],
    },
    {
        "name": "action",
        "token": "demo-member",
        "path": "/api/chat",
        "payload": {"question": "Open a billing review request."},
        "contains": ["pending human approval", "has not been opened", "Approval required"],
        "absent": ["is open"],
        "result": "pending_approval",
    },
    {
        "name": "voice",
        "token": "demo-member",
        "path": "/api/voice",
        "payload": {"transcript": "Can you explain my latest claim?"},
        "contains": ["DEMO-1048", "$75", "$10"],
        "absent": ["OTHER-9001"],
        "member_owes_cents": 8500,
        "speech": "not_used",
    },
]


def run_scorecard(root: Path | None = None) -> dict:
    directory = root or Path(tempfile.mkdtemp(prefix="membercare-eval-"))
    settings = Settings(
        data_dir=default_data_dir(),
        db_path=directory / "lab.db",
        checkpoint_path=directory / "checkpoints.sqlite",
        web_dir=repo_root() / "web",
    )
    results = []
    with TestClient(create_app(settings)) as client:
        for case in CASES:
            response = client.post(case["path"], headers={"Authorization": f"Bearer {case['token']}"}, json=case["payload"])
            body = response.json()
            answer = body.get("answer", "")
            problems = []
            if response.status_code != 200:
                problems.append(f"status {response.status_code}")
            for text in case["contains"]:
                if text not in answer:
                    problems.append(f"missing {text}")
            for text in case["absent"]:
                if text in answer:
                    problems.append(f"unexpected {text}")
            if "member_owes_cents" in case and body.get("computed", {}).get("member_owes_cents") != case["member_owes_cents"]:
                problems.append("member amount mismatch")
            if case.get("result") and body.get("result") != case["result"]:
                problems.append("result mismatch")
            if case.get("speech") and body.get("server_speech_recognizer") != case["speech"]:
                problems.append("speech recognizer was reported as used")
            if body.get("narration") != "template":
                problems.append("narration was not the template")
            results.append({"name": case["name"], "passed": not problems, "problems": problems})
    return {
        "notice": "SYNTHETIC_MEMBER_DATA_NOT_A_HEALTH_PLAN",
        "passed": sum(1 for row in results if row["passed"]),
        "total": len(results),
        "results": results,
    }


def main() -> None:
    report = run_scorecard()
    print(json.dumps(report, indent=2))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
