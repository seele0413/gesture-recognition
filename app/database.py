from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from app.control import (
    DEFAULT_GESTURE_CONFIDENCE_THRESHOLD,
    DEFAULT_MAPPINGS,
    migrate_legacy_mappings,
    validate_gesture_confidence_threshold,
    validate_mappings,
)
from app.settings import MEDIA_DIR


class ControlStore:
    """Persists mappings and bounded, session-scoped controller metadata."""

    MAX_GESTURE_EVENTS = 500
    MAX_WORKFLOW_RUNS = 500
    MAX_WORKFLOW_STEP_RUNS = 5000
    _SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()
        self.clear_temporary()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS controller_sessions (
                    session_id TEXT PRIMARY KEY,
                    track_id TEXT,
                    state TEXT NOT NULL,
                    started_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS gesture_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    gesture TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    handedness TEXT NOT NULL,
                    action TEXT NOT NULL,
                    action_triggered INTEGER NOT NULL,
                    timestamp_ms INTEGER NOT NULL
                )"""
            )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    workflow_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    trigger_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    definition_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_triggers (
                    workflow_id TEXT PRIMARY KEY REFERENCES workflows(workflow_id) ON DELETE CASCADE,
                    trigger_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_versions (
                    workflow_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    definition_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (workflow_id, version)
                );
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    workflow_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    trigger_event_json TEXT,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_workflow_runs_created ON workflow_runs(created_at DESC);
                CREATE TABLE IF NOT EXISTS workflow_step_runs (
                    run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
                    node_id TEXT NOT NULL,
                    action TEXT,
                    command_id TEXT,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    PRIMARY KEY (run_id, node_id)
                );
                CREATE TABLE IF NOT EXISTS media_assets (
                    asset_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS presentation_decks (
                    deck_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    path TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                ("gesture_mappings", json.dumps(DEFAULT_MAPPINGS)),
            )
            connection.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                ("gesture_confidence_threshold", json.dumps(DEFAULT_GESTURE_CONFIDENCE_THRESHOLD)),
            )
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", ("gesture_mappings",)
            ).fetchone()
            stored_mappings = json.loads(row["value"])
            migrated_mappings = migrate_legacy_mappings(stored_mappings)
            if migrated_mappings != stored_mappings:
                connection.execute(
                    "UPDATE settings SET value = ? WHERE key = ?",
                    (json.dumps(migrated_mappings), "gesture_mappings"),
                )
            threshold_row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", ("gesture_confidence_threshold",)
            ).fetchone()
            try:
                validate_gesture_confidence_threshold(json.loads(threshold_row["value"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                connection.execute(
                    "UPDATE settings SET value = ? WHERE key = ?",
                    (json.dumps(DEFAULT_GESTURE_CONFIDENCE_THRESHOLD), "gesture_confidence_threshold"),
                )
            connection.execute(
                "INSERT OR IGNORE INTO media_assets (asset_id, title, filename, enabled) VALUES (?, ?, ?, 1)",
                ("company-promo", "企业宣传片", "company-promo.mp4"),
            )

    def clear_temporary(self, session_id: str | None = None) -> None:
        with self._lock, self._connection() as connection:
            if session_id is None:
                connection.execute("DELETE FROM gesture_events")
                connection.execute("DELETE FROM controller_sessions")
            else:
                connection.execute("DELETE FROM gesture_events WHERE session_id = ?", (session_id,))
                connection.execute("DELETE FROM controller_sessions WHERE session_id = ?", (session_id,))

    def begin_session(self, session_id: str, timestamp_ms: int) -> None:
        self.clear_temporary()
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO controller_sessions (session_id, track_id, state, started_at_ms, updated_at_ms) "
                "VALUES (?, NULL, 'unlocked', ?, ?)",
                (session_id, timestamp_ms, timestamp_ms),
            )

    def update_controller(
        self, session_id: str, state: str, track_id: str | None, timestamp_ms: int
    ) -> None:
        if state not in {"unlocked", "locked", "lost"}:
            raise ValueError("无效的主控状态")
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE controller_sessions SET track_id = ?, state = ?, updated_at_ms = ? WHERE session_id = ?",
                (track_id, state, timestamp_ms, session_id),
            )

    def record_gesture(self, session_id: str, event: dict[str, Any]) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO gesture_events
                   (session_id, track_id, gesture, confidence, handedness, action, action_triggered, timestamp_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    str(event["target_id"]),
                    str(event["gesture"] or ""),
                    float(event["confidence"]),
                    str(event["handedness"]),
                    str(event["action"]),
                    int(bool(event["action_triggered"])),
                    int(event["timestamp_ms"]),
                ),
            )
            connection.execute(
                """DELETE FROM gesture_events WHERE id IN (
                       SELECT id FROM gesture_events WHERE session_id = ?
                       ORDER BY id DESC LIMIT -1 OFFSET ?
                   )""",
                (session_id, self.MAX_GESTURE_EVENTS),
            )

    def get_recent_gestures(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), self.MAX_GESTURE_EVENTS))
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """SELECT track_id, gesture, confidence, handedness, action, action_triggered, timestamp_ms
                   FROM gesture_events WHERE session_id = ? ORDER BY id DESC LIMIT ?""",
                (session_id, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_mappings(self) -> dict[str, str]:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", ("gesture_mappings",)
            ).fetchone()
        return validate_mappings(json.loads(row["value"]))

    def set_mappings(self, mappings: dict[str, str]) -> dict[str, str]:
        clean = validate_mappings(mappings)
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("gesture_mappings", json.dumps(clean)),
            )
        return clean

    def get_gesture_confidence_threshold(self) -> float:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", ("gesture_confidence_threshold",)
            ).fetchone()
        return validate_gesture_confidence_threshold(json.loads(row["value"]))

    def set_gesture_confidence_threshold(self, value: float) -> float:
        threshold = validate_gesture_confidence_threshold(value)
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("gesture_confidence_threshold", json.dumps(threshold)),
            )
        return threshold

    def save_workflow(self, definition: dict[str, Any]) -> dict[str, Any]:
        workflow = dict(definition)
        workflow_id = workflow.get("id")
        if not isinstance(workflow_id, str) or not self._SAFE_ID.fullmatch(workflow_id):
            raise ValueError("工作流 ID 格式无效")
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with self._lock, self._connection() as connection:
            current = connection.execute(
                "SELECT version, created_at, updated_at, definition_json FROM workflows WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
            previous = json.loads(current["definition_json"]) if current else None
            workflow["created_at"] = str(current["created_at"]) if current else workflow.get("created_at", now)
            comparable = {key: value for key, value in workflow.items() if key not in {"version", "created_at", "updated_at"}}
            previous_comparable = {
                key: value for key, value in (previous or {}).items()
                if key not in {"version", "created_at", "updated_at"}
            }
            changed = previous is None or comparable != previous_comparable
            workflow["version"] = int(current["version"]) + 1 if current and changed else (int(current["version"]) if current else 1)
            workflow["updated_at"] = now if changed else str(current["updated_at"])
            encoded = json.dumps(workflow, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            connection.execute(
                """INSERT INTO workflows
                   (workflow_id, name, description, enabled, trigger_json, schema_version, version,
                    definition_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(workflow_id) DO UPDATE SET
                     name=excluded.name, description=excluded.description, enabled=excluded.enabled,
                     trigger_json=excluded.trigger_json, schema_version=excluded.schema_version,
                     version=excluded.version, definition_json=excluded.definition_json,
                     updated_at=excluded.updated_at""",
                (
                    workflow["id"], workflow["name"], workflow.get("description", ""),
                    int(bool(workflow.get("enabled"))), json.dumps(workflow["trigger"], ensure_ascii=False),
                    workflow["schema_version"], workflow["version"], encoded,
                    workflow["created_at"], workflow["updated_at"],
                ),
            )
            connection.execute(
                "INSERT INTO workflow_triggers (workflow_id, trigger_json) VALUES (?, ?) "
                "ON CONFLICT(workflow_id) DO UPDATE SET trigger_json=excluded.trigger_json",
                (workflow["id"], json.dumps(workflow["trigger"], ensure_ascii=False)),
            )
            if changed:
                connection.execute(
                    "INSERT INTO workflow_versions (workflow_id, version, definition_json, created_at) VALUES (?, ?, ?, ?)",
                    (workflow["id"], workflow["version"], encoded, now),
                )
        return workflow

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT definition_json FROM workflows WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
        return json.loads(row["definition_json"]) if row else None

    def get_workflows(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT definition_json FROM workflows"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY updated_at DESC, workflow_id"
        with self._lock, self._connection() as connection:
            rows = connection.execute(query).fetchall()
        return [json.loads(row["definition_json"]) for row in rows]

    def get_workflow_versions(self, workflow_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT version, definition_json, created_at FROM workflow_versions "
                "WHERE workflow_id = ? ORDER BY version DESC", (workflow_id,)
            ).fetchall()
        return [
            {"version": row["version"], "created_at": row["created_at"], "definition": json.loads(row["definition_json"])}
            for row in rows
        ]

    def delete_workflow(self, workflow_id: str) -> bool:
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM workflow_versions WHERE workflow_id = ?", (workflow_id,))
            cursor = connection.execute("DELETE FROM workflows WHERE workflow_id = ?", (workflow_id,))
        return cursor.rowcount > 0

    def get_workflow_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), self.MAX_WORKFLOW_RUNS))
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_runs ORDER BY created_at DESC LIMIT ?", (safe_limit,)
            ).fetchall()
        return [self._decode_workflow_run(row) for row in rows]

    def get_workflow_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            steps = connection.execute(
                "SELECT * FROM workflow_step_runs WHERE run_id = ? ORDER BY started_at, node_id", (run_id,)
            ).fetchall()
        result = self._decode_workflow_run(row)
        result["steps"] = [
            {
                "node_id": step["node_id"], "action": step["action"], "command_id": step["command_id"],
                "status": step["status"], "result": json.loads(step["result_json"]) if step["result_json"] else None,
                "error": step["error"], "started_at": step["started_at"], "finished_at": step["finished_at"],
            }
            for step in steps
        ]
        return result

    @staticmethod
    def _decode_workflow_run(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"], "workflow_id": row["workflow_id"],
            "workflow_version": row["workflow_version"], "status": row["status"], "mode": row["mode"],
            "trigger_event": json.loads(row["trigger_event_json"]) if row["trigger_event_json"] else None,
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"], "created_at": row["created_at"],
            "started_at": row["started_at"], "finished_at": row["finished_at"],
        }

    def create_workflow_run(self, run: dict[str, Any]) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO workflow_runs
                   (run_id, workflow_id, workflow_version, status, mode, trigger_event_json,
                    result_json, error, created_at, started_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run["run_id"], run["workflow_id"], run["workflow_version"], run["status"], run["mode"],
                    json.dumps(run.get("trigger_event"), ensure_ascii=False) if run.get("trigger_event") is not None else None,
                    json.dumps(run.get("result"), ensure_ascii=False) if run.get("result") is not None else None,
                    run.get("error"), run["created_at"], run.get("started_at"), run.get("finished_at"),
                ),
            )
            connection.execute(
                "DELETE FROM workflow_runs WHERE run_id IN (SELECT run_id FROM workflow_runs ORDER BY created_at DESC LIMIT -1 OFFSET ?)",
                (self.MAX_WORKFLOW_RUNS,),
            )

    def update_workflow_run(self, run_id: str, **values: Any) -> None:
        allowed = {"status", "result", "error", "started_at", "finished_at"}
        if not values or set(values) - allowed:
            raise ValueError("工作流运行状态字段无效")
        assignments = []
        parameters: list[Any] = []
        for key, value in values.items():
            column = "result_json" if key == "result" else key
            assignments.append(f"{column} = ?")
            parameters.append(json.dumps(value, ensure_ascii=False) if key == "result" and value is not None else value)
        parameters.append(run_id)
        with self._lock, self._connection() as connection:
            connection.execute(f"UPDATE workflow_runs SET {', '.join(assignments)} WHERE run_id = ?", parameters)

    def save_workflow_step(self, run_id: str, step: dict[str, Any]) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO workflow_step_runs
                   (run_id, node_id, action, command_id, status, result_json, error, started_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, node_id) DO UPDATE SET action=excluded.action,
                     command_id=excluded.command_id, status=excluded.status, result_json=excluded.result_json,
                     error=excluded.error, started_at=excluded.started_at, finished_at=excluded.finished_at""",
                (
                    run_id, step["node_id"], step.get("action"), step.get("command_id"), step["status"],
                    json.dumps(step.get("result"), ensure_ascii=False) if step.get("result") is not None else None,
                    step.get("error"), step["started_at"], step.get("finished_at"),
                ),
            )
            connection.execute(
                "DELETE FROM workflow_step_runs WHERE rowid IN (SELECT rowid FROM workflow_step_runs ORDER BY started_at DESC LIMIT -1 OFFSET ?)",
                (self.MAX_WORKFLOW_STEP_RUNS,),
            )

    def get_media_assets(self) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute("SELECT asset_id, title, filename, enabled FROM media_assets ORDER BY title").fetchall()
        assets = []
        for row in rows:
            asset = self.get_media_asset(row["asset_id"])
            if asset:
                assets.append({
                    "id": row["asset_id"], "title": row["title"],
                    "available": asset["path"].is_file(), "url": f"/media/assets/{row['asset_id']}",
                })
        return assets

    def get_media_asset(self, asset_id: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT asset_id, title, filename, enabled FROM media_assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        if not row or not row["enabled"] or not self._SAFE_ID.fullmatch(row["asset_id"]):
            return None
        if Path(row["filename"]).name != row["filename"]:
            return None
        path = (MEDIA_DIR / row["filename"]).resolve()
        if not path.is_relative_to(MEDIA_DIR.resolve()):
            return None
        return {"id": row["asset_id"], "title": row["title"], "path": path}

    def sync_media_assets(self, assets: dict[str, dict[str, str]]) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("UPDATE media_assets SET enabled = 0")
            for asset_id, item in assets.items():
                if not self._SAFE_ID.fullmatch(asset_id):
                    raise ValueError("媒体 asset_id 格式无效")
                filename = str(item["filename"])
                if Path(filename).name != filename:
                    raise ValueError("媒体文件名必须是单个文件名")
                connection.execute(
                    "INSERT INTO media_assets (asset_id, title, filename, enabled) VALUES (?, ?, ?, 1) "
                    "ON CONFLICT(asset_id) DO UPDATE SET title=excluded.title, filename=excluded.filename, enabled=1",
                    (asset_id, str(item["title"])[:120], filename),
                )

    def sync_presentation_decks(self, decks: dict[str, dict[str, str]]) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("UPDATE presentation_decks SET enabled = 0")
            for deck_id, item in decks.items():
                if not self._SAFE_ID.fullmatch(deck_id):
                    raise ValueError("PPT deck_id 格式无效")
                path = Path(item["path"]).expanduser().resolve()
                connection.execute(
                    "INSERT INTO presentation_decks (deck_id, title, path, enabled) VALUES (?, ?, ?, 1) "
                    "ON CONFLICT(deck_id) DO UPDATE SET title=excluded.title, path=excluded.path, enabled=1",
                    (deck_id, str(item["title"])[:120], str(path)),
                )

    def get_presentations(self) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute("SELECT deck_id, title, path, enabled FROM presentation_decks ORDER BY title").fetchall()
        return [
            {"id": row["deck_id"], "title": row["title"], "available": bool(row["enabled"]) and Path(row["path"]).is_file()}
            for row in rows
            if self._SAFE_ID.fullmatch(row["deck_id"])
        ]

    def get_presentation(self, deck_id: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT deck_id, title, path, enabled FROM presentation_decks WHERE deck_id = ?", (deck_id,)
            ).fetchone()
        if not row or not row["enabled"] or not self._SAFE_ID.fullmatch(row["deck_id"]):
            return None
        return {"id": row["deck_id"], "title": row["title"], "path": Path(row["path"]).resolve()}
