from __future__ import annotations

import math
import time
from typing import Any


DEFAULT_POINTER_SETTINGS = {
    "min_cutoff": 1.0,
    "beta": 0.025,
    "derivative_cutoff": 1.0,
    "press_threshold": 0.36,
    "release_threshold": 0.50,
    "press_stable_frames": 2,
    "release_stable_frames": 2,
    "max_update_hz": 45.0,
    "dropout_grace_ms": 350,
}


def validate_pointer_settings(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("指针设置必须是对象")
    unknown = set(value) - set(DEFAULT_POINTER_SETTINGS)
    if unknown:
        raise ValueError("指针设置包含不支持的字段")
    settings = {**DEFAULT_POINTER_SETTINGS, **value}

    def number(name: str, minimum: float, maximum: float) -> float:
        raw = settings[name]
        if isinstance(raw, bool):
            raise ValueError(f"{name} 必须是数值")
        try:
            result = float(raw)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} 必须是数值") from error
        if not math.isfinite(result) or not minimum <= result <= maximum:
            raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
        return result

    clean = {
        "min_cutoff": number("min_cutoff", 0.1, 10.0),
        "beta": number("beta", 0.0, 1.0),
        "derivative_cutoff": number("derivative_cutoff", 0.1, 10.0),
        "press_threshold": number("press_threshold", 0.05, 0.8),
        "release_threshold": number("release_threshold", 0.1, 0.95),
        "max_update_hz": number("max_update_hz", 10.0, 60.0),
    }
    if clean["press_threshold"] >= clean["release_threshold"]:
        raise ValueError("捏合按下阈值必须小于释放阈值")

    for name in ("press_stable_frames", "release_stable_frames", "dropout_grace_ms"):
        raw = settings[name]
        if isinstance(raw, bool):
            raise ValueError(f"{name} 必须是整数")
        try:
            parsed = int(raw)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} 必须是整数") from error
        if parsed != raw:
            raise ValueError(f"{name} 必须是整数")
        low, high = (1, 5) if name.endswith("_frames") else (50, 1000)
        if not low <= parsed <= high:
            raise ValueError(f"{name} 必须在 {low} 到 {high} 之间")
        clean[name] = parsed
    return clean


class OneEuroFilter:
    """Adaptive low-pass filter: smooth at rest, responsive during fast motion."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.025, derivative_cutoff: float = 1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.derivative_cutoff = float(derivative_cutoff)
        if (
            not math.isfinite(self.min_cutoff) or self.min_cutoff <= 0
            or not math.isfinite(self.beta) or self.beta < 0
            or not math.isfinite(self.derivative_cutoff) or self.derivative_cutoff <= 0
        ):
            raise ValueError("One Euro Filter 参数无效")
        self.reset()

    def reset(self) -> None:
        self._last_timestamp_ms: int | None = None
        self._last_raw_value: float | None = None
        self._filtered_value: float | None = None
        self._filtered_derivative = 0.0

    def filter(self, value: float, timestamp_ms: int) -> float:
        raw = float(value)
        if not math.isfinite(raw):
            raise ValueError("指针坐标必须是有限数值")
        timestamp = int(timestamp_ms)
        if self._last_timestamp_ms is None or self._filtered_value is None or self._last_raw_value is None:
            self._last_timestamp_ms = timestamp
            self._last_raw_value = raw
            self._filtered_value = raw
            self._filtered_derivative = 0.0
            return raw

        elapsed_ms = max(1, timestamp - self._last_timestamp_ms)
        dt = max(1.0 / 240.0, min(0.25, elapsed_ms / 1000.0))
        derivative = (raw - self._last_raw_value) / dt
        derivative_alpha = self._alpha(self.derivative_cutoff, dt)
        self._filtered_derivative = (
            derivative_alpha * derivative + (1.0 - derivative_alpha) * self._filtered_derivative
        )
        cutoff = self.min_cutoff + self.beta * abs(self._filtered_derivative)
        alpha = self._alpha(cutoff, dt)
        filtered = alpha * raw + (1.0 - alpha) * self._filtered_value

        self._last_timestamp_ms = max(timestamp, self._last_timestamp_ms + 1)
        self._last_raw_value = raw
        self._filtered_value = filtered
        return filtered

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(1e-6, cutoff))
        return 1.0 / (1.0 + tau / max(1e-6, dt))


class HandPointerController:
    """Turns one authorized controller hand into a filtered pointer/drag stream."""

    def __init__(
        self,
        press_threshold: float = 0.36,
        release_threshold: float = 0.50,
        smoothing: float | None = None,
        max_update_hz: float = 45.0,
        dropout_grace_ms: int = 350,
        *,
        min_cutoff: float = 1.0,
        beta: float = 0.025,
        derivative_cutoff: float = 1.0,
        press_stable_frames: int = 2,
        release_stable_frames: int = 2,
    ) -> None:
        settings = {
            **DEFAULT_POINTER_SETTINGS,
            "press_threshold": press_threshold,
            "release_threshold": release_threshold,
            "max_update_hz": max_update_hz,
            "dropout_grace_ms": dropout_grace_ms,
            "min_cutoff": min_cutoff,
            "beta": beta,
            "derivative_cutoff": derivative_cutoff,
            "press_stable_frames": press_stable_frames,
            "release_stable_frames": release_stable_frames,
        }
        if smoothing is not None:
            settings["min_cutoff"] = max(0.1, min(10.0, 1.0 / max(0.05, float(smoothing))))
        self.enabled = False
        self._active = False
        self._pressed = False
        self._track_id: str | None = None
        self._handedness: str | None = None
        self._x: float | None = None
        self._y: float | None = None
        self._last_valid_timestamp_ms: int | None = None
        self._controller_id: str | None = None
        self._hand_track_id: str | None = None
        self._identity_confirmed = False
        self._last_emit_at = 0.0
        self._press_candidate_frames = 0
        self._release_candidate_frames = 0
        self._filter_key: tuple[Any, ...] | None = None
        self._x_filter = OneEuroFilter()
        self._y_filter = OneEuroFilter()
        self._settings = validate_pointer_settings(settings)
        self._apply_settings()

    def get_settings(self) -> dict[str, Any]:
        return dict(self._settings)

    def set_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        self._settings = validate_pointer_settings({**self._settings, **settings})
        self._apply_settings()
        self._reset_filters()
        self._press_candidate_frames = 0
        self._release_candidate_frames = 0
        return self.get_settings()

    def _apply_settings(self) -> None:
        self.press_threshold = self._settings["press_threshold"]
        self.release_threshold = self._settings["release_threshold"]
        self.min_update_interval = 1.0 / self._settings["max_update_hz"]
        self.dropout_grace_ms = self._settings["dropout_grace_ms"]
        self.press_stable_frames = self._settings["press_stable_frames"]
        self.release_stable_frames = self._settings["release_stable_frames"]
        self._x_filter = OneEuroFilter(
            self._settings["min_cutoff"], self._settings["beta"], self._settings["derivative_cutoff"]
        )
        self._y_filter = OneEuroFilter(
            self._settings["min_cutoff"], self._settings["beta"], self._settings["derivative_cutoff"]
        )

    def _reset_filters(self) -> None:
        self._x_filter.reset()
        self._y_filter.reset()
        self._filter_key = None

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
        *,
        identity_confirmed: bool = False,
        controller_id: str | None = None,
    ) -> dict[str, Any] | None:
        authorized = controller_state == "locked" or (
            controller_state == "suspect" and identity_confirmed
        )
        if not self.enabled or not authorized or not controller_track_id:
            return self._deactivate(timestamp_ms)

        candidates: list[tuple[dict[str, Any], float, bool]] = []
        for hand in hands:
            if hand.get("track_id") != controller_track_id or hand.get("is_lock_gesture"):
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
                return self._handle_dropout(timestamp_ms)
            hand, pinch_ratio, index_extended = max(
                matching, key=lambda item: float(item[0].get("confidence", 0.0))
            )
        else:
            eligible = [item for item in candidates if item[2] or item[1] <= self.press_threshold]
            if not eligible:
                return self._handle_dropout(timestamp_ms)
            hand, pinch_ratio, index_extended = max(
                eligible, key=lambda item: (item[2], float(item[0].get("confidence", 0.0)))
            )

        was_pressed = self._pressed
        if self._pressed:
            if pinch_ratio >= self.release_threshold:
                self._release_candidate_frames += 1
                if self._release_candidate_frames >= self.release_stable_frames:
                    self._pressed = False
                    self._release_candidate_frames = 0
            else:
                self._release_candidate_frames = 0
        else:
            if pinch_ratio <= self.press_threshold:
                self._press_candidate_frames += 1
                if self._press_candidate_frames >= self.press_stable_frames:
                    self._pressed = True
                    self._press_candidate_frames = 0
            else:
                self._press_candidate_frames = 0

        if not (index_extended or was_pressed or self._pressed or pinch_ratio <= self.press_threshold):
            return self._handle_dropout(timestamp_ms)

        landmarks = hand["landmarks"]
        target_x = min(1.0, max(0.0, self._coordinate(landmarks[8], "x")))
        target_y = min(1.0, max(0.0, self._coordinate(landmarks[8], "y")))
        handedness = str(hand.get("handedness") or "Unknown")
        hand_track_id = hand.get("hand_track_id")
        filter_key = (controller_id, controller_track_id, hand_track_id, handedness)
        if self._filter_key != filter_key:
            self._reset_filters()
            self._filter_key = filter_key
        self._x = self._x_filter.filter(target_x, timestamp_ms)
        self._y = self._y_filter.filter(target_y, timestamp_ms)

        state_changed = (
            not self._active
            or self._pressed != was_pressed
            or handedness != self._handedness
            or controller_track_id != self._track_id
            or controller_id != self._controller_id
            or hand_track_id != self._hand_track_id
        )
        self._active = True
        self._track_id = controller_track_id
        self._handedness = handedness
        self._controller_id = controller_id
        self._hand_track_id = hand_track_id
        self._identity_confirmed = controller_state == "locked" or bool(identity_confirmed)
        self._last_valid_timestamp_ms = int(timestamp_ms)

        now = time.monotonic()
        if not state_changed and now - self._last_emit_at < self.min_update_interval:
            return None
        self._last_emit_at = now
        return self._event(True, self._pressed, timestamp_ms)

    def _handle_dropout(self, timestamp_ms: int) -> dict[str, Any] | None:
        if not self._active:
            self._press_candidate_frames = 0
            self._release_candidate_frames = 0
            return None
        release_event = None
        if self._pressed:
            self._pressed = False
            release_event = self._event(True, False, timestamp_ms)
            self._last_emit_at = time.monotonic()
        self._press_candidate_frames = 0
        self._release_candidate_frames = 0
        last_valid = self._last_valid_timestamp_ms
        if last_valid is not None and int(timestamp_ms) - last_valid <= self.dropout_grace_ms:
            return release_event
        return self._deactivate(timestamp_ms) or release_event

    def _event(self, active: bool, pressed: bool, timestamp_ms: int) -> dict[str, Any]:
        return {
            "type": "pointer",
            "active": bool(active),
            "pressed": bool(pressed),
            "x": round(self._x if self._x is not None else 0.5, 5),
            "y": round(self._y if self._y is not None else 0.5, 5),
            "track_id": self._track_id,
            "handedness": self._handedness,
            "controller_id": self._controller_id,
            "hand_track_id": self._hand_track_id,
            "identity_confirmed": self._identity_confirmed,
            "timestamp_ms": int(timestamp_ms),
        }

    def _deactivate(self, timestamp_ms: int) -> dict[str, Any] | None:
        if not self._active and not self._pressed:
            self._press_candidate_frames = 0
            self._release_candidate_frames = 0
            self._reset_filters()
            return None
        event = self._event(False, False, timestamp_ms)
        self._active = False
        self._pressed = False
        self._track_id = None
        self._handedness = None
        self._controller_id = None
        self._hand_track_id = None
        self._identity_confirmed = False
        self._x = None
        self._y = None
        self._last_valid_timestamp_ms = None
        self._press_candidate_frames = 0
        self._release_candidate_frames = 0
        self._reset_filters()
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
        return math.degrees(math.acos(cosine)) >= 140.0

    @staticmethod
    def _coordinate(point: Any, axis: str) -> float:
        if isinstance(point, dict):
            return float(point[axis])
        return float(getattr(point, axis))

    @classmethod
    def _point(cls, landmark: Any) -> tuple[float, float]:
        return cls._coordinate(landmark, "x"), cls._coordinate(landmark, "y")
