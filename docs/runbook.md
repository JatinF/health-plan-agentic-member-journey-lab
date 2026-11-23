# Runbook

Local only. The module binds to `127.0.0.1` unless you pass another host.

## Start

From the repository root, with the virtual environment installed:

```powershell
Set-Location F:\agy\github\health-plan-agentic-member-journey-lab
.\.venv\Scripts\python.exe -m membercare --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`. The startup log includes `SYNTHETIC_MEMBER_DATA_NOT_A_HEALTH_PLAN`.

`/health/live` means the process is up. `/health/ready` means the synthetic catalogs loaded and their adjudication identities checked.

## Lab actors

The portal lists them. They are fixtures, not accounts.

- `demo-member` reads the Synthetic PPO 2026 records for Alex Rivera.
- `demo-reviewer` can approve or reject a pending billing review for that tenant.
- `other-member` reads a different tenant. Use it to see that the records do not cross.

## Billing review

A member request creates a pending case and pauses the LangGraph thread. The case is not open. Switch the lab actor to the reviewer and choose Approve and open, or call `POST /api/cases/{id}/decision` with `{"decision": "approve"}` and the reviewer token. Reject leaves the case rejected.

Reset local state by stopping the process and deleting the `var` directory.

## Voice

Use Speak when the browser offers a recognizer. Otherwise type the transcript and choose Send transcript. The server field `server_speech_recognizer` stays `not_used`.

## Optional model wording

Leave this unset for the normal lab. To attempt a wording pass that cannot change dollar amounts:

```powershell
$env:MEMBERCARE_NARRATION = "llm"
$env:XAI_API_KEY = "<server-side key>"
```

The call goes to `https://api.x.ai/v1/responses` with model `grok-4.7` and `store` false. If the call fails, or the dollar amounts differ from the template, the template is returned. This workstation run did not set the key and did not make that call.

## Metrics

`GET /metrics` exposes counters. Labels are journey, result, server, and tool. Member ids are not labels.
