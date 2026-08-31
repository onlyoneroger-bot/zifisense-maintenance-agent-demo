from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .core import JudgeContext, TraceRecorder

MODERN_MCP_VERSION = "2026-07-28"


@dataclass(slots=True)
class Response:
    status: int
    headers: dict[str, str]
    body: Any
    elapsed_ms: int
    evidence_ref: str


class ApiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        recorder: TraceRecorder,
        context: JudgeContext,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.recorder = recorder
        self.context = context
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> Response:
        self.context.step()
        request_headers = {"Accept": "application/json", **(headers or {})}
        if authenticated:
            request_headers["Authorization"] = f"Bearer {self.api_key}"
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=request_headers, method=method
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as raw:
                status = raw.status
                response_headers = dict(raw.headers.items())
                payload = raw.read()
        except urllib.error.HTTPError as error:
            status = error.code
            response_headers = dict(error.headers.items())
            payload = error.read()
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        text = payload.decode("utf-8") if payload else ""
        try:
            parsed: Any = json.loads(text) if text else None
        except json.JSONDecodeError:
            parsed = text
        evidence_ref = self.recorder.append(
            {
                "event": "http_exchange",
                "judge_id": self.context.judge_id,
                "request": {
                    "method": method,
                    "path": path,
                    "headers": request_headers,
                    "body": body,
                },
                "response": {
                    "status": status,
                    "headers": response_headers,
                    "body": parsed,
                    "elapsed_ms": elapsed_ms,
                },
            }
        )
        return Response(status, response_headers, parsed, elapsed_ms, evidence_ref)

    def get(self, path: str, **kwargs: Any) -> Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Response:
        return self.request("POST", path, **kwargs)

    def mcp(
        self,
        method: str,
        *,
        params: dict[str, Any] | None = None,
        request_id: int = 1,
        tool_name: str | None = None,
    ) -> Response:
        request_params = dict(params or {})
        request_params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": MODERN_MCP_VERSION,
            "io.modelcontextprotocol/clientInfo": {
                "name": f"zifisense-{self.context.judge_id}",
                "version": "1.0.0",
            },
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        mcp_headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MODERN_MCP_VERSION,
            "Mcp-Method": method,
            "X-Client-Id": f"judge-harness-{self.context.judge_id}",
        }
        if tool_name:
            mcp_headers["Mcp-Name"] = tool_name
        return self.post(
            "/mcp",
            headers=mcp_headers,
            body={
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": request_params,
            },
        )

    def call_tool(
        self, name: str, arguments: dict[str, Any], request_id: int = 1
    ) -> tuple[Response, dict[str, Any]]:
        response = self.mcp(
            "tools/call",
            params={"name": name, "arguments": arguments},
            request_id=request_id,
            tool_name=name,
        )
        structured = response.body.get("result", {}).get("structuredContent", {})
        return response, structured
