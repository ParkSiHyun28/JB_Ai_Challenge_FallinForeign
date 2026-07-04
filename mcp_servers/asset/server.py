"""자산 부문 MCP stdio 서버. tools.py 함수를 MCP tool로 노출한다.
실행: python -m mcp_servers.asset.server"""

import asyncio
import json

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from mcp_servers.asset.tools import TOOL_REGISTRY
from mcp_servers.asset.schemas import TOOL_SCHEMAS

server = Server("liferoad-asset")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=s["name"],
            description=s["description"],
            inputSchema=s["input_schema"],
        )
        for s in TOOL_SCHEMAS.values()
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name not in TOOL_REGISTRY:
        raise ValueError(f"unknown tool: {name}")
    func = TOOL_REGISTRY[name]
    # deadline_radar는 as_of 필수. 없으면 데모 기준일을 채운다.
    # backend(core.run_tool)와 같은 기준일을 써서 어느 경로로 돌려도 수치가 같게 한다.
    if name == "deadline_radar" and "as_of" not in arguments:
        from shared.personas import DEMO_TODAY_STR
        arguments["as_of"] = DEMO_TODAY_STR
    result = func(**arguments)
    return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
