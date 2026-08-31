from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .client import ApiClient
from .core import CheckResult, HarnessReport, JudgeContext, JudgeResult, TraceRecorder
from .judges import run_agent_harness_judge, run_business_judge, run_it_judge
from .reporting import write_reports


def _now() -> str:
    return datetime.now(UTC).isoformat()


def load_profiles(profile_dir: Path | None = None) -> list[dict[str, Any]]:
    root = profile_dir or Path(__file__).with_name("profiles")
    profiles = []
    for path in sorted(root.glob("*.yaml")):
        profiles.append(yaml.safe_load(path.read_text(encoding="utf-8")))
    expected = {"judge_business", "judge_it", "judge_agent_harness"}
    actual = {profile["id"] for profile in profiles}
    if actual != expected:
        raise ValueError(f"Judge profile mismatch: expected {expected}, got {actual}")
    return profiles


def run_harness(
    *,
    base_url: str,
    api_key: str = "dev-evaluator-key",
    limited_api_key: str = "dev-limited-key",
    output_dir: Path | str = Path("reports"),
    seed: int = 20260829,
    run_id: str | None = None,
    timeout: float = 10.0,
) -> HarnessReport:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    resolved_run_id = run_id or uuid.uuid4().hex[:12]
    started_at = _now()
    recorder = TraceRecorder(output / "trace.jsonl")
    judge_results: list[JudgeResult] = []

    for profile in load_profiles():
        ctx = JudgeContext(profile["id"], int(profile["max_steps"]))
        client = ApiClient(base_url, api_key, recorder, ctx, timeout)
        try:
            if profile["id"] == "judge_business":
                run_business_judge(client, ctx, resolved_run_id)
            elif profile["id"] == "judge_it":
                limited = ApiClient(base_url, limited_api_key, recorder, ctx, timeout)
                anonymous = ApiClient(base_url, "", recorder, ctx, timeout)
                run_it_judge(client, limited, anonymous, ctx, resolved_run_id)
            else:
                run_agent_harness_judge(client, ctx, resolved_run_id)
        except Exception as exc:  # The report must survive target or scenario failure.
            ref = recorder.append(
                {
                    "event": "judge_exception",
                    "judge_id": profile["id"],
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            ctx.checks.append(
                CheckResult(
                    check_id=f"{profile['id'].upper()}-RUNTIME",
                    judge_id=profile["id"],
                    category="harness",
                    summary="评委场景必须在步数和超时边界内完成",
                    passed=False,
                    weight=10,
                    hard_fail=True,
                    evidence_refs=[ref],
                    details=f"{type(exc).__name__}: {exc}",
                )
            )
        judge_results.append(
            JudgeResult(
                judge_id=profile["id"],
                name=profile["name"],
                weight=int(profile["weight"]),
                checks=ctx.checks,
            )
        )

    report = HarnessReport(
        run_id=resolved_run_id,
        seed=seed,
        base_url=base_url.rstrip("/"),
        started_at=started_at,
        finished_at=_now(),
        judges=judge_results,
    )
    write_reports(report, output)
    return report
