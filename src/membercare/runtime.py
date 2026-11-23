"""Run one member turn and resume a paused billing review."""

from __future__ import annotations

import time
import uuid

from langgraph.types import Command

from membercare import NOTICE
from membercare.catalog import Actor, Catalog
from membercare.cases import CaseStore
from membercare.domain import classify
from membercare.explain import pending_text
from membercare.graph import McpTools
from membercare.observe import Metrics


DISCLAIMER = (
    "Computed from synthetic plan and explanation-of-benefit records in this lab. "
    "This is not a coverage determination, a bill, or medical advice."
)


class JourneyRunner:
    def __init__(self, graph, catalog: Catalog, cases: CaseStore, tools: McpTools, metrics: Metrics) -> None:
        self.graph = graph
        self.catalog = catalog
        self.cases = cases
        self.tools = tools
        self.metrics = metrics

    async def ask(self, actor: Actor, question: str, channel: str, thread_id: str | None = None) -> dict:
        started = time.perf_counter()
        journey = classify(question)
        if journey == "action":
            pending = self.cases.pending_for_member(actor)
            if pending is not None:
                body = _pending_body(actor, pending, self.catalog)
                self._finish(
                    actor,
                    pending["thread_id"],
                    channel,
                    journey,
                    "pending",
                    "template",
                    started,
                    question,
                    body["answer"],
                )
                return body
            thread_id = thread_id or str(uuid.uuid4())
        else:
            thread_id = thread_id or str(uuid.uuid4())
        try:
            result = await self.graph.ainvoke(_input(actor, question, channel, thread_id), _config(thread_id))
        except Exception as exc:
            if exc.__class__.__name__ != "GraphInterrupt":
                raise
            result = {"__interrupt__": exc.args[0] if exc.args else (), "journey": journey, "tool_trace": []}
        body = _body_from_result(result, thread_id, channel)
        self._finish(
            actor,
            thread_id,
            channel,
            body["journey"],
            body["result"],
            body["narration"],
            started,
            question,
            body["answer"],
        )
        return body

    async def decide(self, actor: Actor, case_id: str, approved: bool) -> dict:
        started = time.perf_counter()
        if actor.role != "reviewer":
            self.metrics.inc("membercare_permission_denied_total", {"result": "decision"})
            self.cases.audit(actor, "decision", "permission_denied", case_id)
            raise PermissionError("a reviewer actor is required")
        case = self.cases.get(actor, case_id)
        thread_id = case["thread_id"]
        if approved:
            approved_case = await self.tools.call(
                "cases",
                "approve_billing_review",
                {"actor_token": actor.token, "case_id": case_id},
            )
            if not approved_case.get("ok"):
                raise PermissionError(approved_case.get("message") or approved_case.get("error") or "approve failed")
        config = _config(thread_id)
        if hasattr(self.graph, "aget_state"):
            snapshot = await self.graph.aget_state(config)
        else:
            snapshot = self.graph.get_state(config)
        if snapshot.next:
            result = await self.graph.ainvoke(
                Command(resume={"approved": approved, "actor_token": actor.token}),
                _config(thread_id),
            )
            body = _body_from_result(result, thread_id, "review")
        else:
            current = self.cases.get(actor, case_id)
            body = {
                "thread_id": thread_id,
                "channel": "review",
                "journey": "action",
                "answer": f"Billing review {current['id']} is {current['status']}.",
                "narration": "template",
                "result": current["status"],
                "pending_action": None,
                "case": _case_view(current),
                "computed": {},
                "tool_trace": [],
                "notice": NOTICE,
                "disclaimer": DISCLAIMER,
                "server_speech_recognizer": "not_used",
            }
        self._finish(
            actor,
            thread_id,
            "review",
            "action",
            body["result"],
            body["narration"],
            started,
            case_id,
            body["answer"],
        )
        return body

    def _finish(self, actor, thread_id, channel, journey, result, narration, started, question, answer: str) -> None:
        elapsed = int((time.perf_counter() - started) * 1000)
        self.metrics.inc("membercare_journey_total", {"journey": journey, "result": result})
        self.cases.record_turn(
            {
                "thread_id": thread_id,
                "tenant_id": actor.tenant_id,
                "actor_id": actor.subject_id,
                "channel": channel,
                "journey": journey,
                "result": result,
                "narration": narration,
                "latency_ms": elapsed,
                "question": question,
                "answer": answer,
            }
        )


def _input(actor: Actor, question: str, channel: str, thread_id: str) -> dict:
    return {
        "tenant_id": actor.tenant_id,
        "actor_token": actor.token,
        "channel": channel,
        "question": question,
        "thread_id": thread_id,
        "tool_trace": [],
    }


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _interrupt_value(result: dict) -> dict | None:
    raw = result.get("__interrupt__")
    if not raw:
        return None
    first = raw[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"status": "pending_approval"}


def _body_from_result(result: dict, thread_id: str, channel: str) -> dict:
    paused = _interrupt_value(result)
    facts = result.get("facts") or {}
    if paused is not None:
        facts = {
            "kind": "action",
            "case_id": paused["case_id"],
            "eob_id": paused["eob_id"],
            "document_title": paused.get("document_title", "Synthetic 2026 Plan Guide"),
            "section_id": "8.1",
            "status": "pending_approval",
        }
        answer = pending_text(facts)
        narration = "template"
        result_name = "pending_approval"
        pending = {"case_id": paused["case_id"], "eob_id": paused["eob_id"], "status": "pending_approval"}
    else:
        answer = result.get("answer") or ""
        narration = result.get("narration") or "template"
        result_name = "ok" if facts.get("kind") not in {None, "denied"} else facts.get("error", "denied")
        pending = None
    computed = {}
    if facts.get("kind") == "claims":
        computed = {
            "copay_cents": facts["copay_cents"],
            "deductible_cents": facts["deductible_cents"],
            "coinsurance_cents": facts["coinsurance_cents"],
            "member_owes_cents": facts["member_owes_cents"],
            "benefit_cents": facts["benefit_cents"],
        }
    return {
        "thread_id": thread_id,
        "channel": channel,
        "journey": result.get("journey") or ("action" if paused else "clarify"),
        "answer": answer,
        "narration": narration,
        "result": result_name,
        "pending_action": pending,
        "case": {"id": facts.get("case_id"), "status": facts.get("status"), "eob_id": facts.get("eob_id")}
        if facts.get("case_id")
        else None,
        "computed": computed,
        "citations_in_answer": "Sources:" in answer,
        "tool_trace": result.get("tool_trace") or [],
        "notice": NOTICE,
        "disclaimer": DISCLAIMER,
        "server_speech_recognizer": "not_used",
    }


def _pending_body(actor: Actor, case: dict, catalog: Catalog) -> dict:
    title = catalog.tenant_for(actor).guide["document_title"]
    facts = {
        "case_id": case["id"],
        "eob_id": case["eob_id"],
        "document_title": title,
        "section_id": "8.1",
    }
    return {
        "thread_id": case["thread_id"],
        "channel": "chat",
        "journey": "action",
        "answer": pending_text(facts),
        "narration": "template",
        "result": "pending_approval",
        "pending_action": {"case_id": case["id"], "eob_id": case["eob_id"], "status": "pending_approval"},
        "case": _case_view(case),
        "computed": {},
        "citations_in_answer": True,
        "tool_trace": [],
        "notice": NOTICE,
        "disclaimer": DISCLAIMER,
        "server_speech_recognizer": "not_used",
    }


def _case_view(case: dict) -> dict:
    return {"id": case["id"], "status": case["status"], "eob_id": case["eob_id"], "thread_id": case["thread_id"]}
