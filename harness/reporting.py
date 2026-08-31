from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .core import HarnessReport


def write_reports(report: HarnessReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    (output_dir / "report.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "report.md").write_text(_markdown(report), encoding="utf-8")
    _write_junit(report, output_dir / "junit.xml")


def _markdown(report: HarnessReport) -> str:
    verdict = "通过" if report.passed else "不通过"
    lines = [
        "# 三评委模拟测试报告",
        "",
        f"- Run ID：`{report.run_id}`",
        f"- 目标：`{report.base_url}`",
        f"- Seed：`{report.seed}`",
        f"- 综合得分：**{report.score}/100**",
        f"- 结论：**{verdict}**",
        "",
        "Fixture 数据只用于比赛模拟；报告证明真实协议和状态流转，不证明已连接真实工业系统。",
        "",
    ]
    for judge in report.judges:
        judge_verdict = "通过" if judge.passed else "硬失败"
        lines.extend(
            [
                f"## {judge.name}",
                "",
                f"得分：**{judge.score}/100**；权重：{judge.weight}%；结论：{judge_verdict}",
                "",
                "| 检查 | 类别 | 结果 | 硬失败 | 证据 |",
                "|---|---|---|---|---|",
            ]
        )
        for check in judge.checks:
            status = "PASS" if check.passed else "FAIL"
            hard = "是" if check.hard_fail else "否"
            evidence = ", ".join(check.evidence_refs)
            lines.append(
                f"| {check.check_id} {check.summary} | {check.category} | "
                f"{status} | {hard} | {evidence} |"
            )
        lines.append("")
    lines.extend(
        [
            "## 证据说明",
            "",
            "`trace.jsonl` 是带前序哈希的 append-only 调用轨迹。"
            "Authorization、Token 和审批挑战等敏感字段已脱敏。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_junit(report: HarnessReport, path: Path) -> None:
    checks = [check for judge in report.judges for check in judge.checks]
    failures = sum(not check.passed for check in checks)
    suite = ET.Element(
        "testsuite",
        {
            "name": "zifisense-judge-harness",
            "tests": str(len(checks)),
            "failures": str(failures),
            "errors": "0",
        },
    )
    for judge in report.judges:
        for check in judge.checks:
            case = ET.SubElement(
                suite,
                "testcase",
                {"classname": judge.judge_id, "name": f"{check.check_id} {check.summary}"},
            )
            if not check.passed:
                failure = ET.SubElement(
                    case,
                    "failure",
                    {"type": "hard-fail" if check.hard_fail else "check-failure"},
                )
                failure.text = check.details or check.summary
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
