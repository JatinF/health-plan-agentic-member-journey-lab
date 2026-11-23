"""LangGraph workflow. Specialized nodes call MCP tools. A reviewer resumes the approval interrupt."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from membercare.domain import benefits_facts, care_facts, claims_facts, classify, named_eob_id, select_claim
from membercare.errors import LabError
from membercare.explain import render
from membercare.narration import narrate


class JourneyState(TypedDict, total=False):
    tenant_id: str
    actor_token: str
    channel: str
    question: str
    thread_id: str
    journey: str
    facts: dict
    answer: str
    narration: str
    approval: dict
    tool_trace: Annotated[list, operator.add]


class McpTools:
    """One in-process MCP session per tool call. The session speaks the MCP client API."""

    def __init__(self, servers: dict, metrics=None) -> None:
        self.servers = servers
        self.metrics = metrics

    async def call(self, server: str, tool: str, args: dict) -> dict:
        from mcp import Client

        async with Client(self.servers[server], raise_exceptions=True) as client:
            result = await client.call_tool(tool, args)
        if result.is_error:
            message = ""
            content = result.content or []
            if content:
                message = getattr(content[0], "text", "") or ""
            if self.metrics is not None:
                self.metrics.inc("membercare_tool_total", {"server": server, "tool": tool, "result": "tool_error"})
            return {"ok": False, "error": "tool_error", "message": message, "payload": {}}
        data = result.structured_content or {}
        if not data and result.content:
            import json

            text = getattr(result.content[0], "text", "") or ""
            if text.startswith("{"):
                data = json.loads(text)
        if isinstance(data, dict) and set(data.keys()) == {"result"} and isinstance(data["result"], dict):
            data = data["result"]
        outcome = "ok" if data.get("ok") else data.get("error", "error")
        if self.metrics is not None:
            self.metrics.inc("membercare_tool_total", {"server": server, "tool": tool, "result": outcome})
        return data


def build_graph(tools: McpTools, checkpointer):
    async def route(state: JourneyState) -> dict:
        journey = classify(state["question"])
        return {
            "journey": journey,
            "tool_trace": [{"server": "router", "tool": "classify", "result": journey}],
        }

    async def benefits(state: JourneyState) -> dict:
        token = state["actor_token"]
        section = await tools.call("plan", "get_plan_section", {"actor_token": token, "section_id": "5.1"})
        searched = await tools.call(
            "plan",
            "search_plan_sections",
            {"actor_token": token, "query": state["question"], "limit": 3},
        )
        coverage = await tools.call("fhir", "get_coverage", {"actor_token": token})
        listed = await tools.call("fhir", "list_explanations", {"actor_token": token})
        trace = _traces(
            ("plan", "get_plan_section", section),
            ("plan", "search_plan_sections", searched),
            ("fhir", "get_coverage", coverage),
            ("fhir", "list_explanations", listed),
        )
        failed = _first_error(section, searched, coverage, listed)
        if failed:
            return {"facts": {"kind": "denied", "error": failed}, "tool_trace": trace}
        if not any(row["id"] == "5.1" for row in searched["payload"]["sections"]):
            return {
                "facts": {"kind": "denied", "error": "not_found"},
                "tool_trace": trace,
            }
        try:
            facts = benefits_facts(
                section["payload"]["section"],
                coverage["payload"]["coverage"],
                listed["payload"]["explanations"],
            )
        except LabError as exc:
            return {"facts": {"kind": "denied", "error": exc.code}, "tool_trace": trace}
        return {"facts": facts, "tool_trace": trace}

    async def claims(state: JourneyState) -> dict:
        token = state["actor_token"]
        listed = await tools.call("fhir", "list_explanations", {"actor_token": token})
        searched = await tools.call(
            "plan",
            "search_plan_sections",
            {"actor_token": token, "query": state["question"], "limit": 3},
        )
        trace = _traces(("fhir", "list_explanations", listed), ("plan", "search_plan_sections", searched))
        failed = _first_error(listed, searched)
        if failed:
            return {"facts": {"kind": "denied", "error": failed}, "tool_trace": trace}
        try:
            chosen, _selection = select_claim(state["question"], listed["payload"]["explanations"])
        except LabError as exc:
            return {"facts": {"kind": "denied", "error": exc.code}, "tool_trace": trace}
        cited_id = "4.2" if chosen["service_category"] == "urgent-care" else "7.2"
        retrieved = {row["id"] for row in searched["payload"]["sections"]}
        if cited_id not in retrieved:
            return {"facts": {"kind": "denied", "error": "not_found"}, "tool_trace": trace}
        guide = await tools.call("plan", "get_plan_section", {"actor_token": token, "section_id": "4.2"})
        calc = await tools.call("plan", "get_plan_section", {"actor_token": token, "section_id": "7.2"})
        trace = trace + _traces(("plan", "get_plan_section", guide), ("plan", "get_plan_section", calc))
        failed = _first_error(guide, calc)
        if failed:
            return {"facts": {"kind": "denied", "error": failed}, "tool_trace": trace}
        try:
            facts = claims_facts(
                state["question"],
                guide["payload"]["section"],
                calc["payload"]["section"],
                listed["payload"]["explanations"],
            )
        except LabError as exc:
            return {"facts": {"kind": "denied", "error": exc.code}, "tool_trace": trace}
        detail = await tools.call(
            "fhir",
            "get_explanation",
            {"actor_token": token, "eob_id": facts["eob_id"]},
        )
        trace = trace + _traces(("fhir", "get_explanation", detail))
        if not detail.get("ok"):
            return {"facts": {"kind": "denied", "error": detail.get("error", "tool_error")}, "tool_trace": trace}
        return {"facts": facts, "tool_trace": trace}

    async def care(state: JourneyState) -> dict:
        token = state["actor_token"]
        searched = await tools.call(
            "plan",
            "search_plan_sections",
            {"actor_token": token, "query": state["question"], "limit": 3},
        )
        section = await tools.call("plan", "get_plan_section", {"actor_token": token, "section_id": "6.1"})
        found = await tools.call(
            "providers",
            "search_providers",
            {"actor_token": token, "specialty": "cardiology", "network_status": "in-network"},
        )
        trace = _traces(
            ("plan", "search_plan_sections", searched),
            ("plan", "get_plan_section", section),
            ("providers", "search_providers", found),
        )
        failed = _first_error(searched, section, found)
        if failed:
            return {"facts": {"kind": "denied", "error": failed}, "tool_trace": trace}
        if not any(row["id"] == "6.1" for row in searched["payload"]["sections"]):
            return {"facts": {"kind": "denied", "error": "not_found"}, "tool_trace": trace}
        facts = care_facts(section["payload"]["section"], found["payload"]["providers"])
        return {"facts": facts, "tool_trace": trace}

    async def action(state: JourneyState) -> dict:
        token = state["actor_token"]
        section = await tools.call("plan", "get_plan_section", {"actor_token": token, "section_id": "8.1"})
        listed = await tools.call("fhir", "list_explanations", {"actor_token": token})
        trace = _traces(("plan", "get_plan_section", section), ("fhir", "list_explanations", listed))
        failed = _first_error(section, listed)
        if failed:
            return {"facts": {"kind": "denied", "error": failed}, "tool_trace": trace}
        selector = state["question"] if named_eob_id(state["question"]) else "latest claim"
        try:
            chosen, _selection = select_claim(selector, listed["payload"]["explanations"])
        except LabError as exc:
            return {"facts": {"kind": "denied", "error": exc.code}, "tool_trace": trace}
        requested = await tools.call(
            "cases",
            "request_billing_review",
            {
                "actor_token": token,
                "eob_id": chosen["id"],
                "reason": "Member requested a billing review",
                "thread_id": state["thread_id"],
            },
        )
        trace = trace + _traces(("cases", "request_billing_review", requested))
        if not requested.get("ok"):
            return {"facts": {"kind": "denied", "error": requested.get("error", "tool_error")}, "tool_trace": trace}
        case = requested["payload"]["case"]
        guide = section["payload"]["section"]
        facts = {
            "kind": "action",
            "case_id": case["id"],
            "eob_id": case["eob_id"],
            "status": case["status"],
            "thread_id": case["thread_id"],
            "section_id": "8.1",
            "document_title": guide["document_title"],
        }
        return {"facts": facts, "tool_trace": trace}

    async def approve_gate(state: JourneyState) -> dict:
        facts = state["facts"]
        decision = interrupt(
            {
                "case_id": facts["case_id"],
                "eob_id": facts["eob_id"],
                "status": "pending_approval",
                "thread_id": facts["thread_id"],
                "document_title": facts["document_title"],
            }
        )
        return {"approval": decision}

    async def open_case(state: JourneyState) -> dict:
        decision = state["approval"]
        opened = await tools.call(
            "cases",
            "open_billing_review",
            {"actor_token": decision["actor_token"], "case_id": state["facts"]["case_id"]},
        )
        facts = dict(state["facts"])
        if opened.get("ok") and opened["payload"]["case"]["status"] == "open":
            facts["kind"] = "action_open"
            facts["status"] = "open"
        else:
            facts = {"kind": "denied", "error": opened.get("error", "approval_required")}
        return {"facts": facts, "tool_trace": _traces(("cases", "open_billing_review", opened))}

    async def reject_case(state: JourneyState) -> dict:
        decision = state["approval"]
        rejected = await tools.call(
            "cases",
            "reject_billing_review",
            {"actor_token": decision["actor_token"], "case_id": state["facts"]["case_id"]},
        )
        facts = dict(state["facts"])
        if rejected.get("ok"):
            facts["kind"] = "action_rejected"
            facts["status"] = "rejected"
        else:
            facts = {"kind": "denied", "error": rejected.get("error", "tool_error")}
        return {"facts": facts, "tool_trace": _traces(("cases", "reject_billing_review", rejected))}

    async def clarify(state: JourneyState) -> dict:
        del state
        return {"facts": {"kind": "clarify"}, "tool_trace": []}

    async def compose(state: JourneyState) -> dict:
        facts = state.get("facts") or {"kind": "clarify"}
        try:
            template = render(facts, state.get("question", ""))
        except LabError:
            template = "The synthetic records are inconsistent, so this lab will not state an amount."
            facts = {"kind": "denied"}
        from membercare.explain import allowed_cents

        text, mode = narrate(template, allowed_cents(facts))
        return {"answer": text, "narration": mode}

    def pick_route(state: JourneyState) -> str:
        return state.get("journey") or "clarify"

    def pick_approval(state: JourneyState) -> str:
        if state.get("approval", {}).get("approved"):
            return "open_case"
        return "reject_case"

    graph = StateGraph(JourneyState)
    graph.add_node("route", route)
    graph.add_node("benefits", benefits)
    graph.add_node("claims", claims)
    graph.add_node("care", care)
    graph.add_node("action", action)
    graph.add_node("approve_gate", approve_gate)
    graph.add_node("open_case", open_case)
    graph.add_node("reject_case", reject_case)
    graph.add_node("clarify", clarify)
    graph.add_node("compose", compose)
    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        pick_route,
        {
            "benefits": "benefits",
            "claims": "claims",
            "care": "care",
            "action": "action",
            "clarify": "clarify",
        },
    )
    graph.add_edge("benefits", "compose")
    graph.add_edge("claims", "compose")
    graph.add_edge("care", "compose")
    graph.add_edge("clarify", "compose")
    graph.add_edge("action", "approve_gate")
    graph.add_conditional_edges(
        "approve_gate",
        pick_approval,
        {"open_case": "open_case", "reject_case": "reject_case"},
    )
    graph.add_edge("open_case", "compose")
    graph.add_edge("reject_case", "compose")
    graph.add_edge("compose", END)
    return graph.compile(checkpointer=checkpointer)


def _traces(*calls: tuple[str, str, dict]) -> list[dict]:
    rows = []
    for server, tool, result in calls:
        rows.append(
            {
                "server": server,
                "tool": tool,
                "result": "ok" if result.get("ok") else result.get("error", "error"),
            }
        )
    return rows


def _first_error(*results: dict) -> str:
    for result in results:
        if not result.get("ok"):
            return result.get("error") or "tool_error"
    return ""
