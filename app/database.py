from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
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


class ControlStore:
    """Persists mappings and bounded, session-scoped controller metadata."""

    MAX_GESTURE_EVENTS = 500

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()
        self.clear_temporary()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
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
