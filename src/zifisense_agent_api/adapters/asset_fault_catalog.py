from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from zifisense_agent_api.domain.entities import AlarmFixture
from zifisense_agent_api.mcp_models import (
    AssetListResult,
    AssetSummary,
    FaultDetailResult,
    FaultHistoryItem,
    FaultHistoryResult,
    FaultListResult,
    FaultSummary,
    MaintenanceHistoryResult,
    MonitoringSummaryResult,
    OperatingContextResult,
    PeerComparisonResult,
)

SEVERITY_ORDER = {"CRITICAL": 4, "MAJOR": 3, "WARNING": 2, "INFO": 1}
DEFAULT_DETAIL_MODULES = {
    "asset",
    "diagnosis",
    "monitoring",
    "operating_context",
    "similar_faults",
    "evidence",
    "conflicts",
    "open_questions",
    "recommended_actions",
}


class AssetFaultCatalog:
    """Deterministic, read-only competition catalog. No LLM is used here."""

    def __init__(self, fixture_dir: Path) -> None:
        catalog_dir = fixture_dir / "catalog"
        self._assets = self._load(catalog_dir / "assets.json")
        self._faults = self._load(catalog_dir / "current_faults.json")
        self._history = self._load(catalog_dir / "fault_history.json")
        self._investigations = self._load_mapping(catalog_dir / "investigation_data.json")
        self._asset_by_id = {item["asset_id"]: item for item in self._assets}
        self._fault_by_id = {item["fault_id"]: item for item in self._faults}

    @staticmethod
    def _load(path: Path) -> list[dict[str, Any]]:
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, list):
            raise ValueError(f"Fixture catalog must contain a JSON array: {path}")
        return data

    @staticmethod
    def _load_mapping(path: Path) -> dict[str, dict[str, Any]]:
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError(f"Fixture catalog must contain a JSON object: {path}")
        return data

    @staticmethod
    def _cursor_offset(cursor: str | None) -> int:
        if not cursor:
            return 0
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
            prefix, raw_offset = decoded.split(":", maxsplit=1)
            if prefix != "offset":
                raise ValueError
            return max(0, int(raw_offset))
        except (ValueError, UnicodeError, base64.binascii.Error) as exc:
            raise ValueError("Invalid pagination cursor.") from exc

    @staticmethod
    def _next_cursor(offset: int, limit: int, total: int) -> str | None:
        next_offset = offset + limit
        if next_offset >= total:
            return None
        return base64.urlsafe_b64encode(f"offset:{next_offset}".encode("ascii")).decode("ascii")

    def _active_faults_for(self, asset_id: str) -> list[dict[str, Any]]:
        return [fault for fault in self._faults if fault["asset_id"] == asset_id]

    def current_fault_for_asset(self, asset_id: str) -> dict[str, Any] | None:
        return next((fault for fault in self._faults if fault["asset_id"] == asset_id), None)

    def current_fault(self, fault_id: str) -> dict[str, Any] | None:
        fault = self._fault_by_id.get(fault_id)
        return dict(fault) if fault is not None else None

    def alarm_fixture_for_fault(self, fault_id: str) -> AlarmFixture:
        """Build an isolated-session fixture from one current catalog fault."""
        fault = self._fault_by_id.get(fault_id)
        if fault is None:
            raise KeyError(fault_id)
        asset = self._asset_by_id[fault["asset_id"]]
        investigation = self._investigations.get(fault_id, {})
        monitoring = investigation.get("monitoring", {})
        measurement_point_id = monitoring.get("measurement_point_id")
        if not measurement_point_id:
            measurement_point_id = asset["measurement_point_ids"][0]
        return AlarmFixture(
            scenario_id=f"catalog_fault:{fault_id}",
            scenario_name=fault["title"],
            scenario_description=(
                f"从活动故障目录 {fault_id} 建立隔离调查会话；"
                "后续结论仍受证据质量、现场同意和人工审批约束。"
            ),
            suggested_questions=(
                "当前证据支持什么判断，还缺什么？",
                "请按顺序给出处置步骤、责任人和升级条件。",
                "是否需要停机，现有证据和企业 SOP 边界是什么？",
            ),
            asset_id=fault["asset_id"],
            asset_name=asset["asset_name"],
            measurement_point_id=measurement_point_id,
            alarm_id=fault["alarm_ids"][0],
            alarm_time=datetime.fromisoformat(fault["detected_at"]),
            severity=fault["severity"],
            diagnosis_text=fault["primary_diagnosis"],
            confidence=float(fault["diagnosis_confidence"]),
            algorithm_version=fault["algorithm_version"],
            source_system=fault["diagnosis_source"],
            evidence_summary=fault["title"],
            is_simulated=True,
        )

    def get_monitoring_summary(self, fault_id: str) -> MonitoringSummaryResult:
        data = self._investigation_section(fault_id, "monitoring")
        return MonitoringSummaryResult(fault_id=fault_id, **data)

    def get_operating_context(self, fault_id: str) -> OperatingContextResult:
        data = self._investigation_section(fault_id, "operating_context")
        return OperatingContextResult(fault_id=fault_id, **data)

    def get_maintenance_history(self, fault_id: str) -> MaintenanceHistoryResult:
        data = self._investigation_section(fault_id, "maintenance")
        return MaintenanceHistoryResult(fault_id=fault_id, **data)

    def compare_peer_assets(self, fault_id: str) -> PeerComparisonResult:
        data = self._investigation_section(fault_id, "peer_comparison")
        return PeerComparisonResult(fault_id=fault_id, **data)

    def _investigation_section(self, fault_id: str, section: str) -> dict[str, Any]:
        investigation = self._investigations.get(fault_id)
        if investigation is None or section not in investigation:
            raise KeyError(fault_id)
        return investigation[section]

    def list_assets(
        self,
        *,
        site_id: str | None = None,
        line_id: str | None = None,
        asset_type: str | None = None,
        monitoring_status: str | None = None,
        has_active_fault: bool | None = None,
        keyword: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> AssetListResult:
        items: list[AssetSummary] = []
        normalized_keyword = keyword.casefold().strip() if keyword else None
        for asset in self._assets:
            active = self._active_faults_for(asset["asset_id"])
            if site_id and asset["site_id"] != site_id:
                continue
            if line_id and asset["line_id"] != line_id:
                continue
            if asset_type and asset["asset_type"] != asset_type:
                continue
            if monitoring_status and asset["monitoring_status"] != monitoring_status:
                continue
            if has_active_fault is not None and bool(active) != has_active_fault:
                continue
            searchable = " ".join(
                [asset["asset_id"], asset["asset_name"], asset["model"]]
            ).casefold()
            if normalized_keyword and normalized_keyword not in searchable:
                continue
            highest = max(
                (fault["severity"] for fault in active),
                key=lambda value: SEVERITY_ORDER[value],
                default=None,
            )
            items.append(
                AssetSummary(
                    **asset,
                    active_fault_count=len(active),
                    highest_active_severity=highest,
                )
            )
        items.sort(
            key=lambda item: (
                -SEVERITY_ORDER.get(item.highest_active_severity or "", 0),
                -item.latest_data_at.timestamp(),
                item.asset_id,
            )
        )
        offset = self._cursor_offset(cursor)
        page = items[offset : offset + limit]
        return AssetListResult(
            items=page,
            total=len(items),
            next_cursor=self._next_cursor(offset, limit, len(items)),
            notice=(
                "active_fault_count=0 only means no active investigation record; "
                "it does not prove that an asset is healthy."
            ),
            is_simulated=True,
        )

    def list_current_faults(
        self,
        *,
        site_id: str | None = None,
        line_id: str | None = None,
        asset_id: str | None = None,
        severity: list[str] | None = None,
        fault_status: list[str] | None = None,
        diagnosis_status: list[str] | None = None,
        detected_from: datetime | None = None,
        detected_to: datetime | None = None,
        requires_human: bool | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> FaultListResult:
        items: list[FaultSummary] = []
        for fault in self._faults:
            asset = self._asset_by_id[fault["asset_id"]]
            detected_at = datetime.fromisoformat(fault["detected_at"])
            if site_id and asset["site_id"] != site_id:
                continue
            if line_id and asset["line_id"] != line_id:
                continue
            if asset_id and fault["asset_id"] != asset_id:
                continue
            if severity and fault["severity"] not in severity:
                continue
            if fault_status and fault["fault_status"] not in fault_status:
                continue
            if diagnosis_status and fault["diagnosis_status"] not in diagnosis_status:
                continue
            if detected_from and detected_at < detected_from:
                continue
            if detected_to and detected_at > detected_to:
                continue
            if requires_human is not None and fault["requires_human"] != requires_human:
                continue
            summary_fields = {
                key: value
                for key, value in fault.items()
                if key
                not in {
                    "diagnosis",
                    "monitoring",
                    "operating_context",
                    "evidence",
                    "conflicts",
                    "open_questions",
                    "recommended_actions",
                }
            }
            items.append(FaultSummary(**summary_fields, asset_name=asset["asset_name"]))
        items.sort(
            key=lambda item: (
                -SEVERITY_ORDER[item.severity],
                -item.latest_update_at.timestamp(),
                item.fault_id,
            )
        )
        offset = self._cursor_offset(cursor)
        page = items[offset : offset + limit]
        return FaultListResult(
            items=page,
            total=len(items),
            next_cursor=self._next_cursor(offset, limit, len(items)),
            is_simulated=True,
        )

    def get_fault_detail(
        self,
        fault_id: str,
        include: list[str] | None = None,
        history_limit: int = 5,
    ) -> FaultDetailResult:
        fault = self._fault_by_id.get(fault_id)
        if fault is None:
            raise KeyError(fault_id)
        asset = self._asset_by_id[fault["asset_id"]]
        modules = set(include) if include else DEFAULT_DETAIL_MODULES
        related_history = self.list_fault_history(
            related_to_fault_id=fault_id, limit=history_limit
        ).items
        diagnosis = fault.get("diagnosis") or {
            "professional_diagnosis": {
                "text": fault["primary_diagnosis"],
                "confidence": fault["diagnosis_confidence"],
                "source_system": fault["diagnosis_source"],
                "algorithm_version": fault["algorithm_version"],
            },
            "confirmed_facts": [
                {
                    "text": f"调查记录由报警 {fault['alarm_ids'][0]} 触发。",
                    "source_system": fault["diagnosis_source"],
                    "observed_at": fault["detected_at"],
                    "evidence_id": f"EVD-{fault['alarm_ids'][0]}",
                }
            ],
            "agent_inferences": [],
            "analysis_summary": (
                f"当前专业系统给出的候选诊断为“{fault['primary_diagnosis']}”，"
                f"诊断成熟度为 {fault['diagnosis_status']}；仍需按下一步行动补充证据。"
            ),
            "limitations": ["当前演示记录仅包含结构化摘要，尚未完成最终工程验证。"],
        }
        monitoring = fault.get("monitoring") or {
            "status": "SUMMARY_ONLY",
            "source_system": fault["diagnosis_source"],
            "latest_update_at": fault["latest_update_at"],
        }
        operating_context = fault.get("operating_context") or {
            "status": "INCOMPLETE",
            "missing_fields": ["报警时负荷", "转速或节拍变化", "近期启停或维修变化"],
        }
        evidence = fault.get("evidence") or [
            {
                "evidence_id": f"EVD-{fault['alarm_ids'][0]}",
                "type": "ALARM",
                "summary": fault["title"],
                "quality_status": "VALID",
                "source_system": fault["diagnosis_source"],
                "is_simulated": True,
            }
        ]
        open_questions = fault.get("open_questions") or [
            "报警前后负荷、转速、节拍或启停工况是否变化？",
            "近期是否进行过维修、调整或传感器操作？",
        ]
        recommended_actions = fault.get("recommended_actions") or [
            {
                "code": "VERIFY_CONTEXT",
                "label": fault["next_action_summary"],
                "requires_approval": fault["requires_human"],
            }
        ]
        core = {
            key: fault[key]
            for key in ("fault_id", "fault_status", "diagnosis_status", "severity", "detected_at")
        }
        return FaultDetailResult(
            fault=core,
            asset=asset if "asset" in modules else None,
            diagnosis=diagnosis if "diagnosis" in modules else None,
            monitoring=monitoring if "monitoring" in modules else None,
            operating_context=(operating_context if "operating_context" in modules else None),
            related_history=related_history if "similar_faults" in modules else [],
            evidence=evidence if "evidence" in modules else [],
            conflicts=fault.get("conflicts", []) if "conflicts" in modules else [],
            open_questions=open_questions if "open_questions" in modules else [],
            recommended_actions=(recommended_actions if "recommended_actions" in modules else []),
            task_id=fault["task_id"],
            is_degraded=False,
            is_simulated=True,
        )

    def list_fault_history(
        self,
        *,
        asset_id: str | None = None,
        site_id: str | None = None,
        line_id: str | None = None,
        asset_type: str | None = None,
        fault_mode: str | None = None,
        diagnosis_status: list[str] | None = None,
        closed_from: datetime | None = None,
        closed_to: datetime | None = None,
        related_to_fault_id: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> FaultHistoryResult:
        items: list[FaultHistoryItem] = []
        for item in self._history:
            closed_at = datetime.fromisoformat(item["closed_at"])
            if asset_id and item["asset_id"] != asset_id:
                continue
            if site_id and item["site_id"] != site_id:
                continue
            if line_id and item["line_id"] != line_id:
                continue
            if asset_type and item["asset_type"] != asset_type:
                continue
            if fault_mode and fault_mode.casefold() not in item["fault_mode"].casefold():
                continue
            if diagnosis_status and item["diagnosis_status"] not in diagnosis_status:
                continue
            if closed_from and closed_at < closed_from:
                continue
            if closed_to and closed_at > closed_to:
                continue
            if related_to_fault_id and related_to_fault_id not in item["related_fault_ids"]:
                continue
            items.append(FaultHistoryItem(**item))
        items.sort(
            key=lambda item: (
                -(item.similarity.score if related_to_fault_id else 0),
                -item.closed_at.timestamp(),
                item.fault_id,
            )
        )
        offset = self._cursor_offset(cursor)
        page = items[offset : offset + limit]
        return FaultHistoryResult(
            items=page,
            total=len(items),
            next_cursor=self._next_cursor(offset, limit, len(items)),
            is_simulated=True,
        )
