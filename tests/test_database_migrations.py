from __future__ import annotations

import sqlite3

from sqlalchemy import inspect

from zifisense_agent_api.infrastructure.database import Database


def test_legacy_sqlite_schema_is_migrated_forward(tmp_path):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE tasks (
            id VARCHAR(64) PRIMARY KEY,
            evaluation_session_id VARCHAR(64) NOT NULL,
            state VARCHAR(64) NOT NULL,
            asset_id VARCHAR(128) NOT NULL,
            created_at VARCHAR(64) NOT NULL
        );
        CREATE TABLE alarm_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alarm_id VARCHAR(128) NOT NULL,
            task_id VARCHAR(64) NOT NULL,
            asset_id VARCHAR(128) NOT NULL,
            measurement_point_id VARCHAR(128) NOT NULL,
            severity VARCHAR(32) NOT NULL,
            diagnosis_text TEXT NOT NULL,
            confidence FLOAT NOT NULL,
            algorithm_version VARCHAR(128) NOT NULL,
            source_system VARCHAR(128) NOT NULL,
            observed_at VARCHAR(64) NOT NULL,
            evidence_id VARCHAR(64) NOT NULL,
            evidence_summary TEXT NOT NULL,
            is_simulated BOOLEAN NOT NULL
        );
        """
    )
    connection.close()

    database = Database(f"sqlite:///{database_path.as_posix()}")
    database.create_schema()
    schema = inspect(database.engine)

    assert "evidence_version" in {
        item["name"] for item in schema.get_columns("tasks")
    }
    assert "external_event_id" in {
        item["name"] for item in schema.get_columns("alarm_events")
    }
    assert "ux_alarm_external_event_id" in {
        item["name"] for item in schema.get_indexes("alarm_events")
    }
    database.close()
