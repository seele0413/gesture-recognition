from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class _HandTrack:
    hand_track_id: str
    handedness: str
    wrist: tuple[float, float]
    velocity: tuple[float, float]
    palm_width: float
    last_seen_ms: int


class HandTrackManager:
    """Short-lived motion continuity for controller hands, not biometric recognition."""

    def __init__(self, *, max_gap_ms: int = 650, max_distance: float = 0.12, ambiguity_margin: float = 0.025):
        if max_gap_ms < 1 or max_distance <= 0 or ambiguity_margin < 0:
            raise ValueError("手部轨迹参数无效")
        self.max_gap_ms = int(max_gap_ms)
        self.max_distance = float(max_distance)
        self.ambiguity_margin = float(ambiguity_margin)
        self._controller_id: str | None = None
        self._tracks: dict[str, _HandTrack] = {}

    def reset(self) -> None:
        self._controller_id = None
        self._tracks.clear()

    def observe_locked(self, hands: list[dict[str, Any]], controller_track_id: str | None,
                       controller_id: str | None, timestamp_ms: int) -> None:
        if not controller_track_id or not controller_id:
            self.reset()
            return
        if self._controller_id != controller_id:
            self.reset()
            self._controller_id = controller_id
        grouped: dict[str, list[tuple[dict[str, Any], tuple[float, float], float]]] = {}
        for hand in hands:
            if hand.get("track_id") != controller_track_id or hand.get("is_lock_gesture"):
                continue
            side = str(hand.get("handedness") or "")
            features = self._features(hand.get("landmarks") or [])
            if side not in {"Left", "Right"} or features is None:
                continue
            wrist, width = features
            grouped.setdefault(side, []).append((hand, wrist, width))
        self._expire(int(timestamp_ms))
        for side, candidates in grouped.items():
            if len(candidates) != 1:
                continue
            hand, wrist, width = candidates[0]
            track = self._tracks.get(side)
            if track is None:
                track = _HandTrack(f"hand-{uuid.uuid4().hex[:12]}", side, wrist, (0.0, 0.0), width, int(timestamp_ms))
                self._tracks[side] = track
            else:
                self._update(track, wrist, width, int(timestamp_ms))
            hand["hand_track_id"] = track.hand_track_id
            hand["identity_confirmed"] = True

    def associate(self, hands: list[dict[str, Any]], controller_track_id: str | None,
                  controller_id: str | None, timestamp_ms: int) -> list[dict[str, Any]]:
        if not controller_track_id or not controller_id or self._controller_id != controller_id:
            return []
        now = int(timestamp_ms)
        self._expire(now)
        grouped: dict[str, list[tuple[int, dict[str, Any], tuple[float, float], float]]] = {}
        for index, hand in enumerate(hands):
            if hand.get("track_id") not in {None, controller_track_id} or hand.get("is_lock_gesture"):
                continue
            side = str(hand.get("handedness") or "")
            features = self._features(hand.get("landmarks") or [])
            if side not in {"Left", "Right"} or features is None:
                continue
            wrist, width = features
            grouped.setdefault(side, []).append((index, hand, wrist, width))
        proposed = []
        for side, track in self._tracks.items():
            elapsed = max(0, now - track.last_seen_ms)
            if elapsed > self.max_gap_ms:
                continue
            predicted_ms = min(elapsed, 200)
            predicted = (track.wrist[0] + track.velocity[0] * predicted_ms,
                         track.wrist[1] + track.velocity[1] * predicted_ms)
            gate = self.max_distance + elapsed / self.max_gap_ms * 0.04
            scored = []
            for index, hand, wrist, width in grouped.get(side, []):
                ratio = width / max(track.palm_width, 1e-6)
                if not 0.55 <= ratio <= 1.8:
                    continue
                distance = math.dist(predicted, wrist)
                if distance > gate:
                    continue
                score = distance + abs(math.log(ratio)) * 0.02
                scored.append((score, index, hand, wrist, width, distance))
            scored.sort(key=lambda item: item[0])
            if not scored or (len(scored) > 1 and scored[1][0] - scored[0][0] < self.ambiguity_margin):
                continue
            _score, index, hand, wrist, width, distance = scored[0]
            proposed.append((side, index, hand, wrist, width, distance))
        counts: dict[int, int] = {}
        for _side, index, *_ in proposed:
            counts[index] = counts.get(index, 0) + 1
        matched = []
        for side, index, hand, wrist, width, distance in proposed:
            if counts[index] != 1:
                continue
            track = self._tracks[side]
            hand["pose_track_id"] = hand.get("track_id")
            hand["track_id"] = controller_track_id
            hand["hand_track_id"] = track.hand_track_id
            hand["identity_confirmed"] = True
            hand["identity_match_distance"] = round(distance, 5)
            hand["association_reason"] = "SUSPECT 阶段手部轨迹连续性唯一匹配"
            self._update(track, wrist, width, now)
            matched.append(hand)
        return matched

    def snapshot(self) -> dict[str, Any]:
        return {"controller_id": self._controller_id, "hand_track_count": len(self._tracks)}

    def _expire(self, now: int) -> None:
        for side in [side for side, track in self._tracks.items() if now - track.last_seen_ms > self.max_gap_ms]:
            del self._tracks[side]

    @staticmethod
    def _update(track: _HandTrack, wrist: tuple[float, float], width: float, now: int) -> None:
        elapsed = max(0, now - track.last_seen_ms)
        if elapsed:
            vx = (wrist[0] - track.wrist[0]) / elapsed
            vy = (wrist[1] - track.wrist[1]) / elapsed
            speed = math.hypot(vx, vy)
            if speed > 0.002:
                scale = 0.002 / speed
                vx *= scale
                vy *= scale
                track.velocity = (track.velocity[0] * 0.5 + vx * 0.5, track.velocity[1] * 0.5 + vy * 0.5)
        track.wrist = wrist
        track.palm_width = track.palm_width * 0.7 + width * 0.3
        track.last_seen_ms = now

    @staticmethod
    def _features(landmarks: list[Any]) -> tuple[tuple[float, float], float] | None:
        if len(landmarks) < 18:
            return None
        try:
            wrist = HandTrackManager._point(landmarks[0])
            palm_a = HandTrackManager._point(landmarks[5])
            palm_b = HandTrackManager._point(landmarks[17])
        except (AttributeError, KeyError, TypeError, ValueError):
            return None
        width = math.dist(palm_a, palm_b)
        if not all(math.isfinite(v) for v in (*wrist, width)) or width < 0.003:
            return None
        return wrist, width

    @staticmethod
    def _point(point: Any) -> tuple[float, float]:
        if isinstance(point, dict):
            return float(point["x"]), float(point["y"])
        return float(point.x), float(point.y)
