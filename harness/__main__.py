from __future__ import annotations

import argparse
import os
from pathlib import Path

from .runner import run_harness


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic three-judge simulation")
    parser.add_argument(
        "--base-url", default=os.getenv("HARNESS_BASE_URL", "http://127.0.0.1:8080")
    )
    parser.add_argument("--api-key", default=os.getenv("HARNESS_API_KEY", "dev-evaluator-key"))
    parser.add_argument(
        "--limited-api-key", default=os.getenv("HARNESS_LIMITED_API_KEY", "dev-limited-key")
    )
    parser.add_argument("--output", type=Path, default=Path("reports"))
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--run-id")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    report = run_harness(
        base_url=args.base_url,
        api_key=args.api_key,
        limited_api_key=args.limited_api_key,
        output_dir=args.output,
        seed=args.seed,
        run_id=args.run_id,
        timeout=args.timeout,
    )
    verdict = "PASS" if report.passed else "FAIL"
    print(f"Judge harness {verdict}: {report.score}/100")
    print(f"Reports: {args.output.resolve()}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
