from __future__ import annotations

import math
import uuid
from typing import Any, Sequence


LOCK_STABLE_FRAMES = 2
LOCK_WINDOW_FRAMES = 5
V_MIN_PALM_WIDTH = 0.005
V_FINGER_EXTENSION_COSINE = 0.15
V_FINGER_FOLDED_COSINE = 0.78
V_FINGER_LENGTH_RATIO = 0.045
V_FINGER_SEPARATION_RATIO = 0.16
CONTROLLER_SUSPECT_GRACE_MS = 650
CONTROLLER_LOST_TIMEOUT_MS = 3500


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


def _finger_cosine(
    landmarks: Sequence[Any], mcp: int, pip: int, tip: int, palm_width: float
) -> float | None:
    base, joint, end = (_xy(landmarks[index]) for index in (mcp, pip, tip))
    if base is None or joint is None or end is None:
        return None
    proximal = (joint[0] - base[0], joint[1] - base[1])
    distal = (end[0] - joint[0], end[1] - joint[1])
    proximal_length = math.hypot(*proximal)
    distal_length = math.hypot(*distal)
    if min(proximal_length, distal_length) < V_FINGER_LENGTH_RATIO * palm_width:
        return None
    cosine = (proximal[0] * distal[0] + proximal[1] * distal[1]) / (proximal_length * distal_length)
    return max(-1.0, min(1.0, cosine))


def _is_extended(
    landmarks: Sequence[Any], mcp: int, pip: int, tip: int, palm_width: float
) -> bool:
    cosine = _finger_cosine(landmarks, mcp, pip, tip, palm_width)
    return cosine is not None and cosine >= V_FINGER_EXTENSION_COSINE


def _is_folded(
    landmarks: Sequence[Any], mcp: int, pip: int, tip: int, palm_width: float
) -> bool:
    cosine = _finger_cosine(landmarks, mcp, pip, tip, palm_width)
    return cosine is not None and cosine < V_FINGER_FOLDED_COSINE


def analyze_v_gesture(landmarks: Sequence[Any]) -> dict[str, Any]:
    """Recognize a V/peace sign from hand geometry, independent of classifier labels."""
    if len(landmarks) != 21:
        return {"is_v": False, "reason": "缺少完整的 21 个手部关键点", "spread_ratio": None}
    point_values = [_xy(point) for point in landmarks]
    if any(point is None for point in point_values):
        return {"is_v": False, "reason": "手部关键点坐标无效", "spread_ratio": None}
    points = [point for point in point_values if point is not None]
    palm_width = _distance(points[5], points[17])
    if palm_width < V_MIN_PALM_WIDTH:
        return {"is_v": False, "reason": "手掌在画面中过小，建议靠近摄像头或提高画面分辨率", "spread_ratio": None}

    if not _is_extended(landmarks, 5, 6, 8, palm_width):
        return {"is_v": False, "reason": "食指未充分伸展", "spread_ratio": None}
    if not _is_extended(landmarks, 9, 10, 12, palm_width):
        return {"is_v": False, "reason": "中指未充分伸展", "spread_ratio": None}

    spread_ratio = _distance(points[8], points[12]) / palm_width
    if spread_ratio < V_FINGER_SEPARATION_RATIO:
        return {
            "is_v": False,
            "reason": f"食指与中指分开幅度不足（{spread_ratio:.2f} 掌宽）",
            "spread_ratio": round(spread_ratio, 3),
        }
    if not _is_folded(landmarks, 13, 14, 16, palm_width):
        return {"is_v": False, "reason": "无名指需要弯曲", "spread_ratio": round(spread_ratio, 3)}
    if not _is_folded(landmarks, 17, 18, 20, palm_width):
        return {"is_v": False, "reason": "小指需要弯曲", "spread_ratio": round(spread_ratio, 3)}

    return {"is_v": True, "reason": "V 字手势几何符合", "spread_ratio": round(spread_ratio, 3)}


def is_v_gesture(landmarks: Sequence[Any]) -> bool:
    return analyze_v_gesture(landmarks)["is_v"]


class ControllerLock:
    """Maintains a stable controller session while its current pose track is reacquired."""

    def __init__(
        self,
        stable_frames: int = LOCK_STABLE_FRAMES,
        window_frames: int = LOCK_WINDOW_FRAMES,
        lost_timeout_ms: int = CONTROLLER_LOST_TIMEOUT_MS,
        suspect_grace_ms: int = CONTROLLER_SUSPECT_GRACE_MS,
    ):
        if stable_frames < 1 or window_frames < stable_frames:
            raise ValueError("主控锁定帧数必须满足 1 <= stable_frames <= window_frames")
        if suspect_grace_ms < 0 or lost_timeout_ms <= suspect_grace_ms:
            raise ValueError("主控恢复时间必须满足 0 <= suspect_grace_ms < lost_timeout_ms")
        self.stable_frames = int(stable_frames)
        self.window_frames = int(window_frames)
        self.lost_timeout_ms = int(lost_timeout_ms)
        self.suspect_grace_ms = int(suspect_grace_ms)
        self.status = "unlocked"
        self.controller_id: str | None = None
        self.track_id: str | None = None
        self.lost_since_ms: int | None = None
        self._candidate_track: str | None = None
        self._candidate_history: list[bool] = []

    def observe_lock_candidates(self, track_ids: Sequence[str | None], now_ms: int) -> str | None:
        # A new candidate must never take over an existing or recovering controller.
        if self.status != "unlocked":
            return None

        if not track_ids:
            if self._candidate_track is None:
                return None
            self._append_candidate(False)
            return self._try_lock()

        if any(track_id is None for track_id in track_ids):
            self._reset_candidate()
            return None
        unique_ids = set(track_ids)
        if len(unique_ids) != 1:
            self._reset_candidate()
            return None

        candidate = next(iter(unique_ids))
        if candidate != self._candidate_track:
            self._reset_candidate()
            self._candidate_track = candidate
        self._append_candidate(True)
        return self._try_lock()

    def _append_candidate(self, detected: bool) -> None:
        self._candidate_history.append(bool(detected))
        if len(self._candidate_history) > self.window_frames:
            self._candidate_history.pop(0)
        if not any(self._candidate_history):
            self._reset_candidate()

    def _try_lock(self) -> str | None:
        if self._candidate_track is None:
            return None
        if sum(self._candidate_history) < self.stable_frames:
            return None
        self.status = "locked"
        self.controller_id = f"controller-{uuid.uuid4().hex[:12]}"
        self.track_id = self._candidate_track
        self.lost_since_ms = None
        self._reset_candidate()
        return "locked"

    def update_tracking(self, visible_track_ids: set[str], now_ms: int) -> list[tuple[str, str]]:
        if self.status == "unlocked" or self.track_id is None:
            return []

        if self.track_id in visible_track_ids:
            if self.status in {"suspect", "reacquiring"}:
                self.status = "locked"
                self.lost_since_ms = None
                return [("locked", "reacquired")]
            return []

        if self.status == "locked":
            self.status = "suspect"
            self.lost_since_ms = int(now_ms)
            return [("suspect", "track_unmatched")]

        assert self.lost_since_ms is not None
        elapsed_ms = max(0, int(now_ms) - self.lost_since_ms)
        if self.status == "suspect" and elapsed_ms >= self.suspect_grace_ms:
            self.status = "reacquiring"
            return [("reacquiring", "track_reacquiring")]

        if elapsed_ms >= self.lost_timeout_ms:
            self.status = "unlocked"
            self.controller_id = None
            self.track_id = None
            self.lost_since_ms = None
            self._reset_candidate()
            return [("unlocked", "track_timeout")]
        return []

    def unlock(self) -> bool:
        changed = self.status != "unlocked"
        self.status = "unlocked"
        self.controller_id = None
        self.track_id = None
        self.lost_since_ms = None
        self._reset_candidate()
        return changed

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.status,
            "controller_id": self.controller_id,
            "track_id": self.track_id,
            "lost_since_ms": self.lost_since_ms,
            "suspect_grace_ms": self.suspect_grace_ms,
            "lost_timeout_ms": self.lost_timeout_ms,
            "lock_progress": sum(self._candidate_history),
            "lock_required_frames": self.stable_frames,
            "lock_window_frames": self.window_frames,
        }

    def _reset_candidate(self) -> None:
        self._candidate_track = None
        self._candidate_history = []
