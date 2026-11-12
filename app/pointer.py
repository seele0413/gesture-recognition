from __future__ import annotations

import math
import time
from typing import Any


class HandPointerController:
    """Turns one locked person's pointing hand into a smoothed web-pointer stream."""

    def __init__(
        self,
        press_threshold: float = 0.28,
        release_threshold: float = 0.38,
        smoothing: float = 0.45,
        max_update_hz: float = 30.0,
    ) -> None:
        if not 0 < press_threshold < release_threshold < 1:
            raise ValueError("捏合阈值必须满足 0 < 按下阈值 < 释放阈值 < 1")
        self.press_threshold = float(press_threshold)
        self.release_threshold = float(release_threshold)
        self.smoothing = min(1.0, max(0.05, float(smoothing)))
        self.min_update_interval = 1.0 / max(1.0, float(max_update_hz))
        self.enabled = False
        self._active = False
        self._pressed = False
        self._track_id: str | None = None
        self._handedness: str | None = None
        self._x: float | None = None
        self._y: float | None = None
        self._last_emit_at = 0.0

    def set_enabled(self, enabled: bool, timestamp_ms: int = 0) -> dict[str, Any] | None:
        self.enabled = bool(enabled)
        if not self.enabled:
            return self._deactivate(timestamp_ms)
        return None

    def reset(self, timestamp_ms: int = 0) -> dict[str, Any] | None:
        return self._deactivate(timestamp_ms)

    def update(
        self,
        hands: list[dict[str, Any]],
        controller_state: str,
        controller_track_id: str | None,
        timestamp_ms: int,
    ) -> dict[str, Any] | None:
        if not self.enabled or controller_state != "locked" or not controller_track_id:
            return self._deactivate(timestamp_ms)

        candidates: list[tuple[dict[str, Any], float, bool]] = []
        for hand in hands:
            if hand.get("track_id") != controller_track_id or hand.get("is_ok"):
                continue
            landmarks = hand.get("landmarks") or []
            if len(landmarks) < 18:
                continue
            pinch_ratio = self._pinch_ratio(landmarks)
            if pinch_ratio is None:
                continue
            index_extended = self._index_extended(landmarks) or hand.get("gesture") == "Pointing_Up"
            candidates.append((hand, pinch_ratio, index_extended))

        if self._handedness is not None:
            matching = [item for item in candidates if item[0].get("handedness") == self._handedness]
            if not matching:
                return self._deactivate(timestamp_ms)
            hand, pinch_ratio, index_extended = matching[0]
        else:
            eligible = [item for item in candidates if item[2] or item[1] <= self.press_threshold]
            if not eligible:
                return self._deactivate(timestamp_ms)
            hand, pinch_ratio, index_extended = max(
                eligible,
                key=lambda item: (item[2], float(item[0].get("confidence", 0.0))),
            )

        pressed = (
            pinch_ratio <= self.release_threshold
            if self._pressed
            else pinch_ratio <= self.press_threshold
        )
        active = bool(index_extended or pressed)
        if not active:
            return self._deactivate(timestamp_ms)

        landmarks = hand["landmarks"]
        target_x = min(1.0, max(0.0, self._coordinate(landmarks[8], "x")))
        target_y = min(1.0, max(0.0, self._coordinate(landmarks[8], "y")))
        if self._x is None or self._y is None:
            self._x, self._y = target_x, target_y
        else:
            self._x += self.smoothing * (target_x - self._x)
            self._y += self.smoothing * (target_y - self._y)

        handedness = str(hand.get("handedness") or "Unknown")
        state_changed = (
            not self._active
            or pressed != self._pressed
            or handedness != self._handedness
            or controller_track_id != self._track_id
        )
        self._active = True
        self._pressed = pressed
        self._track_id = controller_track_id
        self._handedness = handedness

        now = time.monotonic()
        if not state_changed and now - self._last_emit_at < self.min_update_interval:
            return None
        self._last_emit_at = now
        return {
            "type": "pointer",
            "active": True,
            "pressed": pressed,
            "x": round(self._x, 5),
            "y": round(self._y, 5),
            "track_id": controller_track_id,
            "handedness": handedness,
            "timestamp_ms": int(timestamp_ms),
        }

    def _deactivate(self, timestamp_ms: int) -> dict[str, Any] | None:
        if not self._active and not self._pressed:
            return None
        event = {
            "type": "pointer",
            "active": False,
            "pressed": False,
            "x": round(self._x if self._x is not None else 0.5, 5),
            "y": round(self._y if self._y is not None else 0.5, 5),
            "track_id": self._track_id,
            "handedness": self._handedness,
            "timestamp_ms": int(timestamp_ms),
        }
        self._active = False
        self._pressed = False
        self._track_id = None
        self._handedness = None
        self._x = None
        self._y = None
        self._last_emit_at = time.monotonic()
        return event

    @classmethod
    def _pinch_ratio(cls, landmarks: list[Any]) -> float | None:
        thumb = cls._point(landmarks[4])
        index = cls._point(landmarks[8])
        palm_a = cls._point(landmarks[5])
        palm_b = cls._point(landmarks[17])
        palm_width = math.dist(palm_a, palm_b)
        if palm_width < 1e-5:
            return None
        return math.dist(thumb, index) / palm_width

    @classmethod
    def _index_extended(cls, landmarks: list[Any]) -> bool:
        mcp = cls._point(landmarks[5])
        pip = cls._point(landmarks[6])
        tip = cls._point(landmarks[8])
        ax, ay = mcp[0] - pip[0], mcp[1] - pip[1]
        bx, by = tip[0] - pip[0], tip[1] - pip[1]
        denominator = math.hypot(ax, ay) * math.hypot(bx, by)
        if denominator < 1e-6:
            return False
        cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / denominator))
        return math.degrees(math.acos(cosine)) >= 150.0

    @staticmethod
    def _coordinate(point: Any, axis: str) -> float:
        if isinstance(point, dict):
            return float(point[axis])
        return float(getattr(point, axis))

    @classmethod
    def _point(cls, landmark: Any) -> tuple[float, float]:
        return cls._coordinate(landmark, "x"), cls._coordinate(landmark, "y")
