from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe the deployed MCP endpoint with the official SDK."
    )
    parser.add_argument("--url", default=os.getenv("MCP_URL"), help="Full HTTPS MCP URL")
    parser.add_argument("--api-key", default=os.getenv("MCP_API_KEY"), help=argparse.SUPPRESS)
    parser.add_argument("--client-id", default=os.getenv("MCP_CLIENT_ID", "deployment-smoke"))
    parser.add_argument("--expected-tools", type=int, default=17)
    parser.add_argument("--timeout", type=float, default=29.0)
    return parser.parse_args()


async def probe(args: argparse.Namespace) -> dict[str, object]:
    if not args.url or not args.api_key:
        raise ValueError("Set MCP_URL and MCP_API_KEY, or pass --url and --api-key.")
    if not args.url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise ValueError("Remote MCP_URL must use HTTPS.")

    headers = {
        "Authorization": f"Bearer {args.api_key}",
        "X-Client-Id": args.client_id,
    }
    timeout = httpx2.Timeout(args.timeout, connect=min(5.0, args.timeout))
    async with (
        httpx2.AsyncClient(headers=headers, timeout=timeout) as http,
        streamable_http_client(args.url, http_client=http) as (read_stream, write_stream),
        ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=args.timeout,
        ) as session,
    ):
        discovered = await session.discover()
        tools = await session.list_tools()
        call = await session.call_tool("list_assets", {"limit": 2})

    if len(tools.tools) != args.expected_tools:
        raise RuntimeError(
            f"Expected {args.expected_tools} tools but discovered {len(tools.tools)}."
        )
    if call.is_error or not call.structured_content:
        raise RuntimeError("list_assets did not return a successful structured result.")

    return {
        "status": "PASS",
        "protocol_version": session.protocol_version,
        "supported_versions": discovered.supported_versions,
        "tool_count": len(tools.tools),
        "list_assets_total": call.structured_content.get("total"),
        "is_error": call.is_error,
    }


def main() -> int:
    args = parse_args()
    try:
        result = asyncio.run(probe(args))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
