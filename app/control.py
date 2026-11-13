from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Mapping, Sequence
from urllib.parse import urlsplit


GESTURES = (
    "Open_Palm",
    "Closed_Fist",
    "Thumb_Up",
    "Thumb_Down",
    "Pointing_Up",
    "Victory",
    "ILoveYou",
)

ACTIONS = ("none", "play_pause", "volume_up", "volume_down", "mute_toggle")
DEFAULT_GESTURE_CONFIDENCE_THRESHOLD = 0.60
MIN_GESTURE_CONFIDENCE_THRESHOLD = 0.50
MAX_GESTURE_CONFIDENCE_THRESHOLD = 0.90
GESTURE_CONFIDENCE_STEP = 0.05
DEFAULT_MAPPINGS = {
    "Open_Palm": "play_pause",
    "Closed_Fist": "none",
    "Thumb_Up": "volume_up",
    "Thumb_Down": "volume_down",
    "Pointing_Up": "none",
    "Victory": "mute_toggle",
    "ILoveYou": "none",
}
LEGACY_DEFAULT_MAPPINGS = {
    "Open_Palm": "toggle_switch",
    "Closed_Fist": "reset_value",
    "Thumb_Up": "value_plus_10",
    "Thumb_Down": "value_minus_10",
    "Pointing_Up": "none",
    "Victory": "none",
    "ILoveYou": "none",
}
LEGACY_ACTIONS = {
    "toggle_switch": "play_pause",
    "value_plus_10": "volume_up",
    "value_minus_10": "volume_down",
    "reset_value": "none",
}


def migrate_legacy_mappings(value: Mapping[str, str]) -> dict[str, str]:
    if dict(value) == LEGACY_DEFAULT_MAPPINGS:
        return dict(DEFAULT_MAPPINGS)
    return {
        gesture: LEGACY_ACTIONS.get(action, action)
        for gesture, action in value.items()
    }


def validate_mappings(value: Mapping[str, str]) -> dict[str, str]:
    if set(value) != set(GESTURES):
        raise ValueError("映射必须且只能包含所有内置手势")
    if any(action not in ACTIONS for action in value.values()):
        raise ValueError("映射包含不支持的网页动作")
    return {gesture: value[gesture] for gesture in GESTURES}


def validate_gesture_confidence_threshold(value: object) -> float:
    try:
        threshold = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("手势置信度必须是 0.50 到 0.90 之间、步长为 0.05 的数值") from error
    if not math.isfinite(threshold):
        raise ValueError("手势置信度必须是有限数值")
    steps = (threshold - MIN_GESTURE_CONFIDENCE_THRESHOLD) / GESTURE_CONFIDENCE_STEP
    if not MIN_GESTURE_CONFIDENCE_THRESHOLD <= threshold <= MAX_GESTURE_CONFIDENCE_THRESHOLD or not math.isclose(
        steps, round(steps), abs_tol=1e-7
    ):
        raise ValueError("手势置信度必须是 0.50 到 0.90 之间、步长为 0.05 的数值")
    return round(threshold, 2)


def validate_rtsp_url(value: str) -> str:
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
        valid = parsed.scheme.lower() in {"rtsp", "rtsps"} and bool(parsed.hostname)
    except ValueError:
        valid = False
    if not valid or len(candidate) > 2048:
        raise ValueError("请输入有效的 rtsp:// 或 rtsps:// 摄像头地址")
    return candidate


def build_gesture_event(
    *,
    target_id: str,
    target_name: str,
    gesture: str | None,
    confidence: float,
    handedness: str,
    timestamp_ms: int,
    action: str,
    action_triggered: bool,
    landmarks: Sequence[Mapping[str, float]],
) -> dict[str, object]:
    if len(landmarks) != 21:
        raise ValueError("手势事件必须包含 21 个手部关键点")
    if action not in ACTIONS:
        raise ValueError("事件包含不支持的网页动作")
    return {
        "type": "gesture",
        "target_id": target_id,
        "target_name": target_name,
        "gesture": gesture,
        "confidence": float(confidence),
        "handedness": handedness,
        "timestamp_ms": int(timestamp_ms),
        "action": action,
        "action_triggered": bool(action_triggered),
        "landmarks": [dict(point) for point in landmarks],
    }


def build_controller_event(
    *, state: str, track_id: str | None, timestamp_ms: int, reason: str
) -> dict[str, object]:
    if state not in {"unlocked", "locked", "lost"}:
        raise ValueError("无效的主控状态")
    if state == "locked" and not track_id:
        raise ValueError("锁定状态必须包含 track_id")
    return {
        "type": "controller",
        "state": state,
        "track_id": track_id,
        "timestamp_ms": int(timestamp_ms),
        "reason": reason,
    }


@dataclass
class _GestureState:
    label: str | None = None
    frames: int = 0
    emitted_label: str | None = None


class GestureGate:
    """Debounces gestures and rate-limits mapped actions per action type."""

    def __init__(
        self,
        stable_frames: int = 3,
        confidence_threshold: float = DEFAULT_GESTURE_CONFIDENCE_THRESHOLD,
        cooldown_ms: int = 800,
    ):
        self.stable_frames = stable_frames
        self.confidence_threshold = validate_gesture_confidence_threshold(confidence_threshold)
        self.cooldown_ms = cooldown_ms
        self._states: dict[str, _GestureState] = {}
        self._last_action_at: dict[str, int] = {}
        self._last_status: dict[str, dict[str, object]] = {}

    def set_confidence_threshold(self, confidence_threshold: float) -> None:
        self.confidence_threshold = validate_gesture_confidence_threshold(confidence_threshold)
        self._states.clear()
        self._last_status.clear()

    def observe(
        self,
        key: str,
        label: str | None,
        confidence: float,
        action: str,
        now_ms: int | None = None,
    ) -> bool | None:
        state = self._states.setdefault(key, _GestureState())
        if label not in GESTURES or confidence < self.confidence_threshold:
            state.label = None
            state.frames = 0
            state.emitted_label = None
            low_confidence = label in GESTURES
            reason = (
                f"识别置信度不足（{confidence:.0%}，门槛 {self.confidence_threshold:.0%}）"
                if low_confidence
                else "未识别到内置手势"
            )
            self._last_status[key] = {
                "stable_frames": 0,
                "reason": reason,
                "reason_code": "low_confidence" if low_confidence else "unrecognized_gesture",
                "confidence": confidence,
                "confidence_threshold": self.confidence_threshold,
            }
            return None

        if state.label != label:
            state.label = label
            state.frames = 1
            state.emitted_label = None
        else:
            state.frames += 1

        if state.frames < self.stable_frames:
            self._last_status[key] = {
                "stable_frames": state.frames,
                "reason": f"手势稳定确认中（{state.frames}/{self.stable_frames} 帧）",
                "reason_code": "stabilizing",
                "confidence": confidence,
                "confidence_threshold": self.confidence_threshold,
            }
            return None
        if state.emitted_label == label:
            self._last_status[key] = {
                "stable_frames": state.frames,
                "reason": "本次手势已处理，等待手势变化",
                "reason_code": "already_handled",
                "confidence": confidence,
                "confidence_threshold": self.confidence_threshold,
            }
            return None

        state.emitted_label = label
        if action == "none":
            self._last_status[key] = {
                "stable_frames": state.frames,
                "reason": "该手势未映射网页动作",
                "reason_code": "unmapped",
                "confidence": confidence,
                "confidence_threshold": self.confidence_threshold,
            }
            return False

        now = int(time.monotonic() * 1000) if now_ms is None else now_ms
        last_action = self._last_action_at.get(action)
        if last_action is not None and now - last_action < self.cooldown_ms:
            self._last_status[key] = {
                "stable_frames": state.frames,
                "reason": "动作冷却中",
                "reason_code": "cooldown",
                "confidence": confidence,
                "confidence_threshold": self.confidence_threshold,
            }
            return False
        self._last_action_at[action] = now
        self._last_status[key] = {
            "stable_frames": state.frames,
            "reason": "动作已触发",
            "reason_code": "triggered",
            "confidence": confidence,
            "confidence_threshold": self.confidence_threshold,
        }
        return True

    def status(self, key: str) -> dict[str, object]:
        return dict(self._last_status.get(key, {"stable_frames": 0, "reason": "等待手势", "reason_code": "waiting"}))

    def reset_except(self, active_keys: set[str]) -> None:
        for key in list(self._states):
            if key not in active_keys:
                del self._states[key]
                self._last_status.pop(key, None)

    def reset(self, *, preserve_cooldowns: bool = False) -> None:
        self._states.clear()
        self._last_status.clear()
        if not preserve_cooldowns:
            self._last_action_at.clear()
