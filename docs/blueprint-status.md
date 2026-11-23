# Blueprint status

The full project blueprint specifies PostgreSQL, pgvector, Keycloak, a React portal, Synthea-scale data, OpenTelemetry, Docker Compose, and Kubernetes. This tree is the local subset that runs on the workstation. A row below is implemented only when this repository contains the behavior and a test exercises it.

| Blueprint item | This tree |
| --- | --- |
| Five member journeys, with amounts taken from records | Implemented. Chat and a transcript boundary. Pytest and `python -m membercare.evals`. |
| LangGraph supervisor path, specialist nodes, interrupt, SQLite checkpoint | Implemented. One graph routes benefits, claims, care, and billing review. |
| Official MCP Python SDK servers | Implemented. The journey graph calls four in-process servers. Three more servers expose the blueprint tool names and the shared response envelope. |
| FHIR R4-shaped Coverage and ExplanationOfBenefit JSON | Implemented as fixture bundles. No live FHIR server. |
| Human approval before a billing review opens | Implemented. A draft tool writes no case. Submit fails while the case is pending. |
| Idempotent case open | Implemented. Replaying submit on the same case id returns the one open case. |
| Tenant isolation on member reads | Implemented for chat, `/api/v1/me/eobs/{id}`, and `get_eob_details`. |
| Versioned read API | Implemented: `/api/v1/me`, `/api/v1/me/coverage`, `/api/v1/me/eobs`, `/api/v1/me/eobs/{id}`, assistant runs, cases, approvals, and transcript voice. |
| Plan-year filter | Implemented for coverage, benefit lookup, and policy search. A 2025 date does not return the 2026 section. |
| PostgreSQL, pgvector, hybrid retrieval, embeddings | Not implemented. Retrieval is lexical. |
| Keycloak or any OIDC provider | Not implemented. Lab bearer tokens are fixtures. |
| React, TypeScript, Vite | Not implemented. The portal is `web/` HTML, CSS, and JavaScript. |
| Synthea, 100 members, 3 plans, 300 explanations of benefits, 50 providers | Not implemented. Two hand-authored tenants. |
| OpenTelemetry, Jaeger, Grafana, Prometheus server | Not implemented. `/metrics` is an in-process counter page. |
| Speech-to-text, text-to-speech, prerecorded audio, EOB PDF upload | Not implemented. `/api/v1/voice/transcribe` accepts a transcript. |
| Docker Compose, the image, Kubernetes, Helm, Terraform | Files for a single API image only. Not built or applied on this workstation. |
| Ruff, mypy, uv.lock, 100-question golden set, measured P95 | Not run. The acceptance targets in the blueprint are goals, not results. |
| HIPAA or SOC 2 certification | Not claimed. |

The example tool contract in the blueprint uses a different fictional explanation of benefits ($200, $150, $65, $85). DEMO-1048 in this lab is $250 submitted, $180 eligible, $95 plan paid, and $85 member responsibility ($75 copay and $10 deductible). Those figures are the ones the tests reconcile.
