from __future__ import annotations

import math
from uuid import uuid4
from typing import Any


DEFAULT_SUSPECT_GRACE_MS = 800
DEFAULT_REACQUIRE_TIMEOUT_MS = 4000
MIN_REACQUIRE_ASSOCIATION_CONFIDENCE = 0.55
MAX_REACQUIRE_SCORE = 0.50
MIN_REACQUIRE_SCORE_MARGIN = 0.18
MAX_REACQUIRE_CENTER_DISTANCE = 0.65
MAX_REACQUIRE_SHAPE_DISTANCE = 0.55
MAX_REACQUIRE_SIZE_LOG_RATIO = 0.70
MAX_REACQUIRE_PREDICTION_SECONDS = 0.50
MAX_CONTROLLER_SPEED = 1.5
SIGNATURE_LANDMARKS = (11, 12, 13, 14, 15, 16, 23, 24)


def _landmark_visible(point: Any) -> bool:
    visibility = getattr(point, "visibility", 1.0)
    presence = getattr(point, "presence", 1.0)
    return (visibility is None or visibility >= 0.35) and (
        presence is None or presence >= 0.35
    )


class ControllerIdentityManager:
    """Keeps one session-local controller identity across temporary pose-track loss.

    Rebinding to a new pose track is deliberately conservative: it uses pose geometry,
    position prediction, track age and uniqueness. It is not visual person ReID.
    """

    def __init__(
        self,
        suspect_grace_ms: int = DEFAULT_SUSPECT_GRACE_MS,
        reacquire_timeout_ms: int = DEFAULT_REACQUIRE_TIMEOUT_MS,
    ) -> None:
        if suspect_grace_ms < 0 or reacquire_timeout_ms <= suspect_grace_ms:
            raise ValueError("主控恢复时间必须满足 0 <= suspect_grace_ms < reacquire_timeout_ms")
        self.suspect_grace_ms = int(suspect_grace_ms)
        self.reacquire_timeout_ms = int(reacquire_timeout_ms)
        self.reset()

    def reset(self) -> None:
        self.controller_id: str | None = None
        self.track_id: str | None = None
        self.state = "unlocked"
        self.lost_since_ms: int | None = None
        self._anchor: dict[str, Any] | None = None
        self._velocity = (0.0, 0.0)
        self._known_non_controller_track_ids: set[str] = set()
        self.reacquisition_count = 0
        self.last_reacquisition_method: str | None = None
        self.last_reason = "not_locked"
        self._reacquire_candidate_track_id: str | None = None
        self._reacquire_candidate_frames = 0

    def bind(self, track_id: str, tracks: list[dict[str, Any]] | None, now_ms: int) -> str:
        if not track_id:
            raise ValueError("主控身份必须绑定有效的人体轨迹")
        self.controller_id = f"controller-{uuid4().hex[:10]}"
        self.track_id = str(track_id)
        self.state = "locked"
        self.lost_since_ms = None
        self._anchor = None
        self._velocity = (0.0, 0.0)
        self._known_non_controller_track_ids = set()
        self.reacquisition_count = 0
        self.last_reacquisition_method = None
        self.last_reason = "controller_acquired"
        self._reset_reacquire_candidate()
        for track in tracks or []:
            candidate_id = track.get("track_id")
            if candidate_id and candidate_id != self.track_id:
                self._known_non_controller_track_ids.add(str(candidate_id))
            elif candidate_id == self.track_id:
                self._update_anchor(track, int(now_ms))
        return self.controller_id

    def update_tracks(self, tracks: list[dict[str, Any]], now_ms: int) -> list[tuple[str, str]]:
        if self.state == "unlocked" or self.track_id is None:
            return []
        now_ms = int(now_ms)
        if self.lost_since_ms is not None and now_ms - self.lost_since_ms >= self.reacquire_timeout_ms:
            self._expire()
            return [("unlocked", "track_timeout")]

        current = next(
            (
                track for track in tracks
                if track.get("track_id") == self.track_id and not track.get("ambiguous", False)
            ),
            None,
        )
        if current is not None:
            was_missing = self.state in {"suspect", "reacquiring"}
            self.state = "locked"
            self.lost_since_ms = None
            if was_missing:
                self.reacquisition_count += 1
                self.last_reacquisition_method = "same_track"
                self.last_reason = "reacquired_same_track"
            self._remember_other_tracks(tracks)
            self._update_anchor(current, now_ms)
            return [("locked", "reacquired_same_track")] if was_missing else []

        if self.state == "locked":
            self.state = "suspect"
            self.lost_since_ms = now_ms
            self.last_reason = "track_unmatched"
            return [("suspect", "track_unmatched")]

        assert self.lost_since_ms is not None
        elapsed_ms = now_ms - self.lost_since_ms
        if elapsed_ms >= self.suspect_grace_ms:
            candidate = self._find_reacquisition_candidate(tracks, now_ms)
            if candidate is not None:
                candidate_id = str(candidate["track_id"])
                if candidate_id == self._reacquire_candidate_track_id:
                    self._reacquire_candidate_frames += 1
                else:
                    self._reacquire_candidate_track_id = candidate_id
                    self._reacquire_candidate_frames = 1
                if self._reacquire_candidate_frames >= 2:
                    self.track_id = candidate_id
                    self.state = "locked"
                    self.lost_since_ms = None
                    self.reacquisition_count += 1
                    self.last_reacquisition_method = "pose_geometry"
                    self.last_reason = "reacquired_new_track"
                    self._velocity = (0.0, 0.0)
                    self._anchor = None
                    self._reset_reacquire_candidate()
                    self._remember_other_tracks(tracks)
                    self._update_anchor(candidate, now_ms)
                    return [("locked", "track_id_rebound")]
            else:
                self._reset_reacquire_candidate()
            if self.state == "suspect":
                self.state = "reacquiring"
                self.last_reason = "track_reacquiring"
                return [("reacquiring", "track_reacquiring")]
        return []

    def update_track_ids(self, visible_track_ids: set[str], now_ms: int) -> list[tuple[str, str]]:
        """Compatibility path for callers that only have IDs, without pose features."""
        if self.state == "unlocked" or self.track_id is None:
            return []
        now_ms = int(now_ms)
        if self.lost_since_ms is not None and now_ms - self.lost_since_ms >= self.reacquire_timeout_ms:
            self._expire()
            return [("unlocked", "track_timeout")]
        if self.track_id in visible_track_ids:
            was_missing = self.state in {"suspect", "reacquiring"}
            self.state = "locked"
            self.lost_since_ms = None
            if was_missing:
                self.reacquisition_count += 1
                self.last_reacquisition_method = "same_track"
                self.last_reason = "reacquired_same_track"
                return [("locked", "reacquired_same_track")]
            return []
        if self.state == "locked":
            self.state = "suspect"
            self.lost_since_ms = now_ms
            self.last_reason = "track_unmatched"
            return [("suspect", "track_unmatched")]
        if self.state == "suspect" and self.lost_since_ms is not None:
            if now_ms - self.lost_since_ms >= self.suspect_grace_ms:
                self.state = "reacquiring"
                self.last_reason = "track_reacquiring"
                return [("reacquiring", "track_reacquiring")]
        return []

    def snapshot(self) -> dict[str, Any]:
        deadline = (
            self.lost_since_ms + self.reacquire_timeout_ms
            if self.lost_since_ms is not None
            else None
        )
        return {
            "state": self.state,
            "controller_id": self.controller_id,
            "track_id": self.track_id,
            "lost_since_ms": self.lost_since_ms,
            "recovery_deadline_ms": deadline,
            "suspect_grace_ms": self.suspect_grace_ms,
            "reacquire_timeout_ms": self.reacquire_timeout_ms,
            "reacquisition_count": self.reacquisition_count,
            "last_reacquisition_method": self.last_reacquisition_method,
            "last_reason": self.last_reason,
            "reacquisition_candidate_track_id": self._reacquire_candidate_track_id,
            "reacquisition_candidate_frames": self._reacquire_candidate_frames,
            "reacquisition_required_frames": 2,
        }

    def _remember_other_tracks(self, tracks: list[dict[str, Any]]) -> None:
        for track in tracks:
            candidate_id = track.get("track_id")
            if candidate_id and candidate_id != self.track_id:
                self._known_non_controller_track_ids.add(str(candidate_id))

    def _update_anchor(self, track: dict[str, Any], now_ms: int) -> None:
        signature = self._signature(track, now_ms)
        if signature is None:
            return
        if self._anchor is not None:
            elapsed = max(0.033, (now_ms - int(self._anchor["timestamp_ms"])) / 1000.0)
            measured_x = (signature["center"][0] - self._anchor["center"][0]) / elapsed
            measured_y = (signature["center"][1] - self._anchor["center"][1]) / elapsed
            speed = math.hypot(measured_x, measured_y)
            if speed > MAX_CONTROLLER_SPEED:
                factor = MAX_CONTROLLER_SPEED / speed
                measured_x *= factor
                measured_y *= factor
            self._velocity = (
                0.65 * self._velocity[0] + 0.35 * measured_x,
                0.65 * self._velocity[1] + 0.35 * measured_y,
            )
        signature["timestamp_ms"] = now_ms
        self._anchor = signature

    @staticmethod
    def _signature(track: dict[str, Any], timestamp_ms: int) -> dict[str, Any] | None:
        try:
            center = (float(track["center"][0]), float(track["center"][1]))
            box = tuple(float(value) for value in track["box_norm"])
            confidence = float(track.get("association_confidence", 1.0))
        except (KeyError, TypeError, ValueError, IndexError):
            return None
        if len(box) != 4 or not all(math.isfinite(value) for value in (*center, *box, confidence)):
            return None
        width, height = box[2], box[3]
        if width <= 0 or height <= 0:
            return None
        scale = max(width, height, 0.08)
        landmarks = track.get("landmarks") or []
        shape: dict[int, tuple[float, float]] = {}
        for index in SIGNATURE_LANDMARKS:
            if index >= len(landmarks) or not _landmark_visible(landmarks[index]):
                continue
            try:
                x, y = float(landmarks[index].x), float(landmarks[index].y)
            except (AttributeError, TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                shape[index] = ((x - center[0]) / scale, (y - center[1]) / scale)
        return {
            "center": center,
            "box": box,
            "scale": scale,
            "shape": shape,
            "confidence": confidence,
            "first_seen_ms": int(track.get("first_seen_ms", timestamp_ms)),
            "timestamp_ms": int(timestamp_ms),
        }

    def _find_reacquisition_candidate(
        self, tracks: list[dict[str, Any]], now_ms: int
    ) -> dict[str, Any] | None:
        if self._anchor is None or self.lost_since_ms is None:
            return None
        elapsed_seconds = max(0.0, (now_ms - int(self._anchor["timestamp_ms"])) / 1000.0)
        prediction_seconds = min(elapsed_seconds, MAX_REACQUIRE_PREDICTION_SECONDS)
        predicted_center = (
            self._anchor["center"][0] + self._velocity[0] * prediction_seconds,
            self._anchor["center"][1] + self._velocity[1] * prediction_seconds,
        )
        ranked: list[tuple[float, dict[str, Any]]] = []
        for track in tracks:
            track_id = track.get("track_id")
            if not track_id or track.get("ambiguous", False) or track_id == self.track_id:
                continue
            if str(track_id) in self._known_non_controller_track_ids:
                continue
            candidate = self._signature(track, now_ms)
            if candidate is None or candidate["confidence"] < MIN_REACQUIRE_ASSOCIATION_CONFIDENCE:
                continue
            if candidate["first_seen_ms"] < self.lost_since_ms - 100:
                continue
            score = self._match_score(self._anchor, candidate, predicted_center)
            if score is not None and score <= MAX_REACQUIRE_SCORE:
                ranked.append((score, track))
        ranked.sort(key=lambda item: item[0])
        if not ranked:
            return None
        if len(ranked) > 1 and ranked[1][0] - ranked[0][0] < MIN_REACQUIRE_SCORE_MARGIN:
            return None
        return ranked[0][1]

    @staticmethod
    def _match_score(
        anchor: dict[str, Any], candidate: dict[str, Any], predicted_center: tuple[float, float]
    ) -> float | None:
        center_distance = math.hypot(
            candidate["center"][0] - predicted_center[0],
            candidate["center"][1] - predicted_center[1],
        ) / max(anchor["scale"], candidate["scale"], 0.08)
        shared = anchor["shape"].keys() & candidate["shape"].keys()
        if len(shared) < 3:
            return None
        shape_distance = sum(
            math.hypot(
                anchor["shape"][index][0] - candidate["shape"][index][0],
                anchor["shape"][index][1] - candidate["shape"][index][1],
            )
            for index in shared
        ) / len(shared)
        size_log_ratio = abs(math.log(candidate["scale"] / anchor["scale"]))
        anchor_aspect = anchor["box"][2] / max(anchor["box"][3], 1e-6)
        candidate_aspect = candidate["box"][2] / max(candidate["box"][3], 1e-6)
        aspect_log_ratio = abs(math.log(max(candidate_aspect, 1e-6) / max(anchor_aspect, 1e-6)))
        if center_distance > MAX_REACQUIRE_CENTER_DISTANCE:
            return None
        if shape_distance > MAX_REACQUIRE_SHAPE_DISTANCE:
            return None
        if size_log_ratio > MAX_REACQUIRE_SIZE_LOG_RATIO or aspect_log_ratio > 0.85:
            return None
        return 0.45 * center_distance + 0.40 * shape_distance + 0.10 * size_log_ratio + 0.05 * aspect_log_ratio

    def _reset_reacquire_candidate(self) -> None:
        self._reacquire_candidate_track_id = None
        self._reacquire_candidate_frames = 0

    def _expire(self) -> None:
        self._reset_reacquire_candidate()
        self.state = "unlocked"
        self.controller_id = None
        self.track_id = None
        self.lost_since_ms = None
        self._anchor = None
        self._velocity = (0.0, 0.0)
        self._known_non_controller_track_ids.clear()
        self.last_reason = "track_timeout"
        self.last_reacquisition_method = None
