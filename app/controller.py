from __future__ import annotations

import math
from typing import Any, Sequence


LOCK_STABLE_FRAMES = 5
LOCK_TIP_DISTANCE_RATIO = 0.25
FINGER_EXTENSION_COSINE = 0.55
FINGER_EXTENSION_LENGTH_RATIO = 0.08
CONTROLLER_LOST_TIMEOUT_MS = 2000


def _xy(point: Any) -> tuple[float, float] | None:
    try:
        x, y = float(point.x), float(point.y)
    except (AttributeError, TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return x, y


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _is_extended(landmarks: Sequence[Any], mcp: int, pip: int, tip: int, palm_width: float) -> bool:
    base, joint, end = (_xy(landmarks[index]) for index in (mcp, pip, tip))
    if base is None or joint is None or end is None:
        return False
    proximal = (joint[0] - base[0], joint[1] - base[1])
    distal = (end[0] - joint[0], end[1] - joint[1])
    proximal_length = math.hypot(*proximal)
    distal_length = math.hypot(*distal)
    if min(proximal_length, distal_length) < FINGER_EXTENSION_LENGTH_RATIO * palm_width:
        return False
    cosine = (proximal[0] * distal[0] + proximal[1] * distal[1]) / (proximal_length * distal_length)
    return cosine >= FINGER_EXTENSION_COSINE


def analyze_ok_gesture(
    landmarks: Sequence[Any], tip_distance_ratio: float = LOCK_TIP_DISTANCE_RATIO
) -> dict[str, Any]:
    """Recognize an OK sign and explain the first failed geometry check."""
    if len(landmarks) != 21:
        return {"is_ok": False, "reason": "缺少完整的 21 个手部关键点", "tip_ratio": None}
    point_values = [_xy(point) for point in landmarks]
    if any(point is None for point in point_values):
        return {"is_ok": False, "reason": "手部关键点坐标无效", "tip_ratio": None}
    points = [point for point in point_values if point is not None]
    palm_width = _distance(points[5], points[17])
    if palm_width < 0.015:
        return {"is_ok": False, "reason": "手掌太小或掌宽无法估计", "tip_ratio": None}
    measured_ratio = _distance(points[4], points[8]) / palm_width
    if measured_ratio > tip_distance_ratio:
        return {
            "is_ok": False,
            "reason": f"拇指与食指指尖距离偏大（{measured_ratio:.2f} 掌宽，需不超过 {tip_distance_ratio:.2f}）",
            "tip_ratio": round(measured_ratio, 3),
        }
    for name, (mcp, pip, tip) in zip(
        ("中指", "无名指", "小指"), ((9, 10, 12), (13, 14, 16), (17, 18, 20))
    ):
        if not _is_extended(landmarks, mcp, pip, tip, palm_width):
            return {
                "is_ok": False,
                "reason": f"{name}未充分伸展",
                "tip_ratio": round(measured_ratio, 3),
            }
    return {"is_ok": True, "reason": "OK 手势几何符合", "tip_ratio": round(measured_ratio, 3)}


def is_ok_gesture(landmarks: Sequence[Any], tip_distance_ratio: float = LOCK_TIP_DISTANCE_RATIO) -> bool:
    return analyze_ok_gesture(landmarks, tip_distance_ratio)["is_ok"]


class ControllerLock:
    """Locks control to one session-local pose track after a stable OK sign."""

    def __init__(
        self,
        stable_frames: int = LOCK_STABLE_FRAMES,
        lost_timeout_ms: int = CONTROLLER_LOST_TIMEOUT_MS,
    ):
        self.stable_frames = stable_frames
        self.lost_timeout_ms = lost_timeout_ms
        self.status = "unlocked"
        self.track_id: str | None = None
        self.lost_since_ms: int | None = None
        self._candidate_track: str | None = None
        self._candidate_frames = 0

    def observe_lock_candidates(self, track_ids: Sequence[str | None], now_ms: int) -> str | None:
        if self.status != "unlocked":
            return None
        if not track_ids or any(track_id is None for track_id in track_ids):
            self._reset_candidate()
            return None
        unique_ids = set(track_ids)
        if len(unique_ids) != 1:
            self._reset_candidate()
            return None
        candidate = next(iter(unique_ids))
        if self._candidate_track != candidate:
            self._candidate_track = candidate
            self._candidate_frames = 1
        else:
            self._candidate_frames += 1
        if self._candidate_frames < self.stable_frames:
            return None
        self.status = "locked"
        self.track_id = candidate
        self.lost_since_ms = None
        self._reset_candidate()
        return "locked"

    def update_tracking(self, visible_track_ids: set[str], now_ms: int) -> list[tuple[str, str]]:
        if self.status == "unlocked" or self.track_id is None:
            return []
        if self.track_id in visible_track_ids:
            if self.status == "lost":
                self.status = "locked"
                self.lost_since_ms = None
                return [("locked", "reacquired")]
            return []
        if self.status == "locked":
            self.status = "lost"
            self.lost_since_ms = now_ms
            return [("lost", "track_unmatched")]
        assert self.lost_since_ms is not None
        if now_ms - self.lost_since_ms >= self.lost_timeout_ms:
            self.status = "unlocked"
            self.track_id = None
            self.lost_since_ms = None
            self._reset_candidate()
            return [("unlocked", "track_timeout")]
        return []

    def unlock(self) -> bool:
        changed = self.status != "unlocked"
        self.status = "unlocked"
        self.track_id = None
        self.lost_since_ms = None
        self._reset_candidate()
        return changed

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.status,
            "track_id": self.track_id,
            "lost_since_ms": self.lost_since_ms,
            "lock_progress": self._candidate_frames,
            "lock_required_frames": self.stable_frames,
        }

    def _reset_candidate(self) -> None:
        self._candidate_track = None
        self._candidate_frames = 0
