from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from time import perf_counter

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an MCP SDK concurrency and throughput probe.")
    parser.add_argument("--url", default=os.getenv("MCP_URL"), help="Full HTTPS MCP URL")
    parser.add_argument("--api-key", default=os.getenv("MCP_API_KEY"), help=argparse.SUPPRESS)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--connections", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=29.0)
    parser.add_argument("--min-qps", type=float, default=0.0)
    parser.add_argument("--max-p95-ms", type=float, default=29000.0)
    return parser.parse_args()


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


async def probe(args: argparse.Namespace) -> dict[str, object]:
    if not args.url or not args.api_key:
        raise ValueError("Set MCP_URL and MCP_API_KEY, or pass --url and --api-key.")
    if args.requests < 1 or args.concurrency < 1 or args.connections < 1:
        raise ValueError("requests, concurrency, and connections must be positive.")

    limits = httpx2.Limits(
        max_connections=args.connections,
        max_keepalive_connections=args.connections,
    )
    headers = {
        "Authorization": f"Bearer {args.api_key}",
        "X-Client-Id": "deployment-load-probe",
    }
    latencies: list[float] = []
    failures: list[str] = []
    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(args.requests):
        queue.put_nowait(index)

    async with (
        httpx2.AsyncClient(
            headers=headers,
            timeout=httpx2.Timeout(args.timeout, connect=min(5.0, args.timeout)),
            limits=limits,
            http2=True,
        ) as http,
        streamable_http_client(args.url, http_client=http) as (read_stream, write_stream),
        ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=args.timeout,
        ) as session,
    ):
        await session.discover()

        async def worker() -> None:
            while True:
                try:
                    request_index = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                started = perf_counter()
                try:
                    result = await session.call_tool("list_assets", {"limit": 2})
                    if result.is_error or not result.structured_content:
                        failures.append(f"request {request_index}: tool error")
                except Exception as exc:
                    failures.append(f"request {request_index}: {type(exc).__name__}")
                else:
                    latencies.append((perf_counter() - started) * 1000)
                finally:
                    queue.task_done()

        started_all = perf_counter()
        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        elapsed = perf_counter() - started_all

    successes = len(latencies)
    qps = successes / elapsed if elapsed > 0 else 0.0
    report = {
        "status": "PASS" if not failures else "FAIL",
        "requests": args.requests,
        "successes": successes,
        "failures": len(failures),
        "connections": args.connections,
        "concurrency": args.concurrency,
        "elapsed_seconds": round(elapsed, 3),
        "qps": round(qps, 2),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 2) if latencies else None,
            "p50": round(percentile(latencies, 0.50), 2) if latencies else None,
            "p95": round(percentile(latencies, 0.95), 2) if latencies else None,
            "p99": round(percentile(latencies, 0.99), 2) if latencies else None,
        },
        "failure_samples": failures[:5],
    }
    if (
        failures
        or qps < args.min_qps
        or not latencies
        or percentile(latencies, 0.95) > args.max_p95_ms
    ):
        report["status"] = "FAIL"
    return report


def main() -> int:
    args = parse_args()
    try:
        report = asyncio.run(probe(args))
    except Exception as exc:
        report = {"status": "FAIL", "error": str(exc)}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
