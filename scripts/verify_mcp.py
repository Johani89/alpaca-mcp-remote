"""Smoke-test a deployed MCP endpoint and print the discovered tool names."""

from __future__ import annotations

import argparse
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def verify(url: str) -> None:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            print("\n".join(tool.name for tool in result.tools))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Full MCP URL, including the token query parameter")
    args = parser.parse_args()
    asyncio.run(verify(args.url))


if __name__ == "__main__":
    main()
