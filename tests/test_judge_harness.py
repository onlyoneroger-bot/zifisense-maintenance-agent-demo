from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.core import TraceRecorder
from harness.runner import load_profiles, run_harness


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_service(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    root = Path(__file__).resolve().parents[1]
    python = Path(os.environ.get("VIRTUAL_ENV", root / ".venv"))
    executable = python / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    port = _free_port()
    data_dir = tmp_path_factory.mktemp("judge-harness-service")
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{(data_dir / 'agent.db').as_posix()}"
    environment["RATE_LIMIT_TOTAL_PER_MINUTE"] = "1000"
    environment["RATE_LIMIT_AGENT_PER_MINUTE"] = "1000"
    environment["RATE_LIMIT_MCP_PER_MINUTE"] = "1000"
    environment["LLM_ENABLED"] = "false"
    environment["API_CLIENTS_JSON"] = ""
    process = subprocess.Popen(
        [
            str(executable),
            "-m",
            "uvicorn",
            "zifisense_agent_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(f"uvicorn exited early with code {process.returncode}")
            try:
                with urllib.request.urlopen(f"{base_url}/health", timeout=0.2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("uvicorn did not become healthy")
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_profiles_are_deterministic_and_weighted() -> None:
    profiles = load_profiles()
    assert sum(profile["weight"] for profile in profiles) == 100
    assert all(profile["llm_enabled"] is False for profile in profiles)
    assert all(profile["max_steps"] <= 50 for profile in profiles)


def test_trace_is_hash_chained_and_redacted(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    recorder = TraceRecorder(path)
    recorder.append({"authorization": "Bearer secret", "value": 1})
    recorder.append({"approval_challenge": "one-time-secret", "value": 2})
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["authorization"] == "[REDACTED]"
    assert lines[1]["approval_challenge"] == "[REDACTED]"
    assert lines[1]["previous_hash"] == lines[0]["hash"]
    assert lines[0]["sequence"] == 1
    assert lines[1]["sequence"] == 2


def test_three_judges_pass_against_live_service(live_service: str, tmp_path: Path) -> None:
    output = tmp_path / "reports"
    report = run_harness(
        base_url=live_service,
        output_dir=output,
        run_id="pytest-run-001",
        timeout=5,
    )

    assert report.passed, [
        (check.check_id, check.details)
        for judge in report.judges
        for check in judge.checks
        if not check.passed
    ]
    assert report.score == 100
    assert {judge.judge_id for judge in report.judges} == {
        "judge_business",
        "judge_it",
        "judge_agent_harness",
    }
    assert all(judge.score == 100 for judge in report.judges)
    assert {path.name for path in output.iterdir()} == {
        "report.json",
        "report.md",
        "junit.xml",
        "trace.jsonl",
    }
    trace = output.joinpath("trace.jsonl").read_text(encoding="utf-8")
    assert "dev-evaluator-key" not in trace
    assert '"approval_challenge": "[REDACTED]"' in trace
