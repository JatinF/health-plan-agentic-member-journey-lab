import asyncio
import sys

from membercare.catalog import default_data_dir


def test_plan_guide_stdio_server(tmp_path) -> None:
    asyncio.run(_search(tmp_path))


async def _search(tmp_path) -> None:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "membercare.mcp.plan_guide"],
        env={
            "MEMBERCARE_DATA": str(default_data_dir()),
            "MEMBERCARE_VAR": str(tmp_path),
            "MEMBERCARE_DB": str(tmp_path / "lab.db"),
            "PYTHONPATH": str(default_data_dir().parents[1]),
        },
    )
    async with Client(params) as client:
        listed = await client.list_tools()
        names = {tool.name for tool in listed.tools}
        assert "search_plan_sections" in names
        result = await client.call_tool(
            "search_plan_sections",
            {"actor_token": "demo-member", "query": "urgent care copay", "limit": 2},
        )
    assert result.is_error is False
    payload = result.structured_content
    if isinstance(payload, dict) and set(payload.keys()) == {"result"}:
        payload = payload["result"]
    assert payload["ok"] is True
    assert payload["payload"]["sections"][0]["id"] == "4.2"
