"""Member portal API. The actor token comes from the request, never from the question text."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from membercare import NOTICE
from membercare.catalog import load_catalog
from membercare.cases import CaseStore
from membercare.config import Settings
from membercare.contracts import envelope
from membercare.errors import LabError
from membercare.graph import McpTools, build_graph
from membercare.mcp.servers import build_servers
from membercare.observe import Metrics
from membercare.runtime import DISCLAIMER, JourneyRunner
from membercare.services import Services


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class VoiceIn(BaseModel):
    transcript: str = Field(min_length=1, max_length=1000)


class DecisionIn(BaseModel):
    decision: str


class Limiter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window = [stamp for stamp in self.hits.get(key, []) if now - stamp < 60]
        if len(window) >= self.limit:
            self.hits[key] = window
            return False
        window.append(now)
        self.hits[key] = window
        return True


def create_app(settings: Settings | None = None, rate_limit: int = 60) -> FastAPI:
    settings = settings or Settings.from_env()
    catalog = load_catalog(settings.data_dir)
    metrics = Metrics()
    cases = CaseStore(settings.db_path)
    services = Services(catalog, cases, metrics)
    servers = build_servers(services)
    tools = McpTools(servers, metrics)
    limiter = Limiter(rate_limit)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_path)) as saver:
            app.state.graph = build_graph(tools, saver)
            app.state.runner = JourneyRunner(app.state.graph, catalog, cases, tools, metrics)
            yield
        cases.close()

    app = FastAPI(title="MemberCare AI lab", lifespan=lifespan)
    app.state.catalog = catalog
    app.state.cases = cases
    app.state.services = services
    app.state.metrics = metrics
    app.state.limiter = limiter
    app.state.notice = NOTICE

    def raise_lab(exc: LabError) -> None:
        status = {
            "not_found": 404,
            "permission_denied": 403,
            "invalid": 400,
            "approval_required": 409,
            "inconsistent": 409,
        }.get(exc.code, 409)
        raise HTTPException(status_code=status, detail={"error": exc.code, "message": exc.message})

    def actor_from(request: Request):
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="lab bearer token required")
        token = header.split(" ", 1)[1].strip()
        actor = catalog.actor(token)
        if actor is None:
            raise HTTPException(status_code=401, detail="unknown lab actor")
        if not limiter.allow(actor.subject_id):
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        return actor

    @app.get("/health/live")
    def live() -> dict:
        return {"status": "live", "notice": NOTICE}

    @app.get("/health/ready")
    def ready() -> dict:
        return {
            "status": "ready",
            "notice": NOTICE,
            "tenants": sorted(catalog.tenants),
            "disclaimer": DISCLAIMER,
        }

    @app.get("/metrics")
    def metrics_text() -> PlainTextResponse:
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.get("/api/demo/actors")
    def demo_actors() -> dict:
        return {
            "notice": NOTICE,
            "warning": "These are lab tokens for synthetic records, not an identity provider.",
            "actors": [
                {
                    "token": actor.token,
                    "role": actor.role,
                    "tenant_id": actor.tenant_id,
                    "display_name": actor.display_name,
                }
                for actor in catalog.actors.values()
            ],
        }

    @app.post("/api/chat")
    async def chat(body: ChatIn, request: Request) -> dict:
        actor = actor_from(request)
        metrics.inc("membercare_http_requests_total", {"route": "chat", "result": "accepted"})
        return await request.app.state.runner.ask(actor, body.question.strip(), "chat")

    @app.post("/api/voice")
    @app.post("/api/v1/voice/transcribe")
    async def voice(body: VoiceIn, request: Request) -> dict:
        actor = actor_from(request)
        metrics.inc("membercare_http_requests_total", {"route": "voice", "result": "accepted"})
        result = await request.app.state.runner.ask(actor, body.transcript.strip(), "voice")
        result["server_speech_recognizer"] = "not_used"
        return result

    @app.get("/api/v1/me")
    def member_profile(request: Request) -> dict:
        actor = actor_from(request)
        try:
            data, source = services.member_profile(actor.token)
        except LabError as exc:
            raise_lab(exc)
        return envelope("get_member_profile", data, source)

    @app.get("/api/v1/me/coverage")
    def member_coverage(
        request: Request,
        service_date: str = Query(default="2026-03-02", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict:
        actor = actor_from(request)
        try:
            data, source = services.active_coverage(actor.token, service_date)
        except LabError as exc:
            raise_lab(exc)
        return envelope("get_active_coverage", data, source)

    @app.get("/api/v1/me/eobs")
    def member_eobs(
        request: Request,
        limit: int = Query(default=20, ge=1, le=50),
        cursor: str | None = None,
    ) -> dict:
        actor = actor_from(request)
        try:
            data, source = services.list_member_eobs(actor.token, limit, cursor)
        except LabError as exc:
            raise_lab(exc)
        return envelope("list_member_eobs", data, source)

    @app.get("/api/v1/me/eobs/{eob_id}")
    def member_eob(eob_id: str, request: Request) -> dict:
        actor = actor_from(request)
        try:
            data, source = services.eob_details(actor.token, eob_id)
        except LabError as exc:
            raise_lab(exc)
        return envelope("get_eob_details", data, source)

    @app.post("/api/v1/assistant/runs")
    async def start_run(body: ChatIn, request: Request) -> dict:
        actor = actor_from(request)
        metrics.inc("membercare_http_requests_total", {"route": "assistant_runs", "result": "accepted"})
        result = await request.app.state.runner.ask(actor, body.question.strip(), "chat")
        result["id"] = result["thread_id"]
        return result

    @app.get("/api/v1/assistant/runs/{thread_id}")
    def get_run(thread_id: str, request: Request) -> dict:
        actor = actor_from(request)
        row = cases.turn_for_actor(actor, thread_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"error": "not_found", "message": "run was not found"})
        return {"notice": NOTICE, "run": row}

    @app.get("/api/cases")
    @app.get("/api/v1/cases")
    def list_cases(request: Request) -> dict:
        actor = actor_from(request)
        return {
            "cases": [
                {
                    "id": case["id"],
                    "status": case["status"],
                    "eob_id": case["eob_id"],
                    "thread_id": case["thread_id"],
                    "created_at": case["created_at"],
                }
                for case in cases.list_cases(actor)
            ]
        }

    @app.post("/api/cases/{case_id}/decision")
    @app.post("/api/v1/approvals/{case_id}/decision")
    async def decision(case_id: str, body: DecisionIn, request: Request) -> dict:
        actor = actor_from(request)
        if body.decision not in {"approve", "reject"}:
            raise HTTPException(status_code=400, detail="decision must be approve or reject")
        try:
            return await request.app.state.runner.decide(actor, case_id, body.decision == "approve")
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            if exc.__class__.__name__ == "LabError":
                status = 404 if getattr(exc, "code", "") == "not_found" else 409
                raise HTTPException(status_code=status, detail=exc.message) from exc
            raise

    if settings.web_dir.exists():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
    return app


def app() -> FastAPI:
    return create_app()
