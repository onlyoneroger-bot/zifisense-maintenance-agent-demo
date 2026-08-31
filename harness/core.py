from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SENSITIVE_KEYS = {
    "authorization",
    "approval_challenge",
    "api_key",
    "access_token",
    "token",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


@dataclass(slots=True)
class CheckResult:
    check_id: str
    judge_id: str
    category: str
    summary: str
    passed: bool
    weight: int
    hard_fail: bool = False
    evidence_refs: list[str] = field(default_factory=list)
    details: str = ""


@dataclass(slots=True)
class JudgeResult:
    judge_id: str
    name: str
    weight: int
    checks: list[CheckResult]

    @property
    def score(self) -> float:
        possible = sum(check.weight for check in self.checks)
        earned = sum(check.weight for check in self.checks if check.passed)
        return round(100 * earned / possible, 2) if possible else 0.0

    @property
    def passed(self) -> bool:
        return not any(check.hard_fail and not check.passed for check in self.checks)


@dataclass(slots=True)
class HarnessReport:
    run_id: str
    seed: int
    base_url: str
    started_at: str
    finished_at: str
    judges: list[JudgeResult]

    @property
    def score(self) -> float:
        total_weight = sum(judge.weight for judge in self.judges)
        weighted = sum(judge.score * judge.weight for judge in self.judges)
        return round(weighted / total_weight, 2) if total_weight else 0.0

    @property
    def passed(self) -> bool:
        return all(judge.passed for judge in self.judges) and self.score >= 80

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for index, judge in enumerate(self.judges):
            result["judges"][index]["score"] = judge.score
            result["judges"][index]["passed"] = judge.passed
        result["score"] = self.score
        result["passed"] = self.passed
        return result


class StepLimitExceeded(RuntimeError):
    pass


class TraceRecorder:
    """Append-only JSONL recorder with a tamper-evident hash chain."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._previous_hash = "0" * 64
        self._sequence = 0
        self.path.write_text("", encoding="utf-8")

    def append(self, event: dict[str, Any]) -> str:
        with self._lock:
            self._sequence += 1
            body = {
                "sequence": self._sequence,
                "timestamp": utc_now(),
                "previous_hash": self._previous_hash,
                **redact(event),
            }
            canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            body["hash"] = digest
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
            self._previous_hash = digest
            return f"trace:{self._sequence}"


class JudgeContext:
    def __init__(self, judge_id: str, max_steps: int) -> None:
        self.judge_id = judge_id
        self.max_steps = max_steps
        self.steps = 0
        self.checks: list[CheckResult] = []

    def step(self) -> None:
        self.steps += 1
        if self.steps > self.max_steps:
            raise StepLimitExceeded(
                f"{self.judge_id} exceeded configured step limit {self.max_steps}"
            )

    def check(
        self,
        check_id: str,
        category: str,
        summary: str,
        condition: bool,
        *,
        weight: int = 1,
        hard_fail: bool = False,
        evidence_refs: list[str] | None = None,
        details: str = "",
    ) -> None:
        self.checks.append(
            CheckResult(
                check_id=check_id,
                judge_id=self.judge_id,
                category=category,
                summary=summary,
                passed=bool(condition),
                weight=weight,
                hard_fail=hard_fail,
                evidence_refs=evidence_refs or [],
                details=details,
            )
        )
