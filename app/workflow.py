from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


WORKFLOW_SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_workflow(name: str = "新建工作流") -> dict:
    now = utc_now()
    return {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "id": uuid4().hex,
        "name": name,
        "description": "",
        "enabled": False,
        "trigger": {"type": "gesture_trigger", "gesture": "Open_Palm"},
        "nodes": [
            {"id": "play", "type": "action", "action": "video.play", "params": {}, "timeout_ms": 3000, "on_error": "stop", "position": {"x": 170, "y": 80}},
            {"id": "end", "type": "end", "params": {}, "position": {"x": 470, "y": 80}},
        ],
        "edges": [{"source": "play", "target": "end"}],
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
