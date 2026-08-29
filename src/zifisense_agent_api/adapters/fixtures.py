from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from zifisense_agent_api.domain.entities import AlarmFixture


class FixtureCatalog:
    def __init__(self, fixture_dir: Path) -> None:
        self._fixture_dir = fixture_dir

    def load_alarm_scenario(self, scenario_id: str) -> AlarmFixture:
        if scenario_id != "reducer_gear_alarm_v1":
            raise KeyError(scenario_id)
        path = self._fixture_dir / "scenarios" / f"{scenario_id}.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        alarm = raw["alarm"]
        scenario = raw["scenario"]
        return AlarmFixture(
            scenario_id=scenario["scenario_id"],
            scenario_name=scenario["name"],
            scenario_description=scenario["description"],
            suggested_questions=tuple(scenario["suggested_questions"]),
            asset_id=alarm["asset_id"],
            asset_name=alarm["asset_name"],
            measurement_point_id=alarm["measurement_point_id"],
            alarm_id=alarm["alarm_id"],
            alarm_time=datetime.fromisoformat(alarm["alarm_time"]),
            severity=alarm["severity"],
            diagnosis_text=alarm["diagnosis_text"],
            confidence=float(alarm["confidence"]),
            algorithm_version=alarm["algorithm_version"],
            source_system=alarm["source_system"],
            evidence_summary=alarm["evidence_summary"],
            is_simulated=bool(alarm["is_simulated"]),
        )
