from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


POSE_VISIBILITY_THRESHOLD = 0.35
MAX_TRACK_GAP_MS = 2000
MAX_ASSOCIATION_COST = 1.4
AMBIGUITY_MARGIN = 0.18
MIN_TRACK_CONFIDENCE = 0.45


def _visible(landmark: Any) -> bool:
    visibility = getattr(landmark, "visibility", 1.0)
    presence = getattr(landmark, "presence", 1.0)
    return (visibility is None or visibility >= POSE_VISIBILITY_THRESHOLD) and (
        presence is None or presence >= POSE_VISIBILITY_THRESHOLD
    )


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    left_x2, left_y2 = left[0] + left[2], left[1] + left[3]
    right_x2, right_y2 = right[0] + right[2], right[1] + right[3]
    width = max(0.0, min(left_x2, right_x2) - max(left[0], right[0]))
    height = max(0.0, min(left_y2, right_y2) - max(left[1], right[1]))
    intersection = width * height
    union = left[2] * left[3] + right[2] * right[3] - intersection
    return intersection / union if union > 0 else 0.0


@dataclass
class _Track:
    track_id: str
    center: tuple[float, float]
    box: tuple[float, float, float, float]
    torso: tuple[tuple[int, tuple[float, float]], ...]
    last_seen_ms: int


class PoseTrackManager:
    """Assign session-local IDs to poses and reject ambiguous matches."""

    def __init__(self, max_gap_ms: int = MAX_TRACK_GAP_MS):
        self.max_gap_ms = max_gap_ms
        self._tracks: dict[str, _Track] = {}
        self._next_id = 1

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1

    def update(
        self, poses: list[list[Any]], frame_width: int, frame_height: int, timestamp_ms: int
    ) -> list[dict[str, Any]]:
        self._tracks = {
            track_id: track
            for track_id, track in self._tracks.items()
            if timestamp_ms - track.last_seen_ms <= self.max_gap_ms
        }
        observations = [self._features(index, pose) for index, pose in enumerate(poses)]
        observations = [item for item in observations if item is not None]
        tracks = list(self._tracks.values())
        costs = [[self._cost(track, observation) for observation in observations] for track in tracks]
        ambiguous_tracks: set[int] = set()
        ambiguous_observations: set[int] = set()

        for observation_index in range(len(observations)):
            ranked = sorted((costs[t][observation_index], t) for t in range(len(tracks)))
            if len(ranked) > 1 and ranked[0][0] <= MAX_ASSOCIATION_COST:
                if ranked[1][0] - ranked[0][0] < AMBIGUITY_MARGIN:
                    ambiguous_observations.add(observation_index)
                    ambiguous_tracks.update(index for cost, index in ranked[:2] if cost <= MAX_ASSOCIATION_COST)
        for track_index in range(len(tracks)):
            ranked = sorted((costs[track_index][o], o) for o in range(len(observations)))
            if len(ranked) > 1 and ranked[0][0] <= MAX_ASSOCIATION_COST:
                if ranked[1][0] - ranked[0][0] < AMBIGUITY_MARGIN:
                    ambiguous_tracks.add(track_index)
                    ambiguous_observations.update(index for cost, index in ranked[:2] if cost <= MAX_ASSOCIATION_COST)

        pairs = sorted(
            (costs[t][o], t, o)
            for t in range(len(tracks))
            for o in range(len(observations))
            if costs[t][o] <= MAX_ASSOCIATION_COST
            and 1.0 - costs[t][o] / MAX_ASSOCIATION_COST >= MIN_TRACK_CONFIDENCE
            and t not in ambiguous_tracks
            and o not in ambiguous_observations
        )
        assigned_tracks: set[int] = set()
        assigned_observations: set[int] = set()
        observation_tracks: dict[int, tuple[str, float]] = {}
        for cost, track_index, observation_index in pairs:
            if track_index in assigned_tracks or observation_index in assigned_observations:
                continue
            track = tracks[track_index]
            observation = observations[observation_index]
            self._tracks[track.track_id] = _Track(
                track_id=track.track_id,
                center=observation["center"],
                box=observation["box"],
                torso=observation["torso"],
                last_seen_ms=timestamp_ms,
            )
            observation_tracks[observation_index] = (
                track.track_id,
                max(0.0, 1.0 - cost / MAX_ASSOCIATION_COST),
            )
            assigned_tracks.add(track_index)
            assigned_observations.add(observation_index)

        for observation_index, observation in enumerate(observations):
            if observation_index in assigned_observations or observation_index in ambiguous_observations:
                continue
            if any(
                costs[track_index][observation_index] <= MAX_ASSOCIATION_COST
                for track_index in range(len(tracks))
            ):
                ambiguous_observations.add(observation_index)
                continue
            track_id = f"person-{self._next_id}"
            self._next_id += 1
            self._tracks[track_id] = _Track(
                track_id=track_id,
                center=observation["center"],
                box=observation["box"],
                torso=observation["torso"],
                last_seen_ms=timestamp_ms,
            )
            observation_tracks[observation_index] = (track_id, 1.0)

        results = []
        for observation_index, observation in enumerate(observations):
            track = observation_tracks.get(observation_index)
            x, y, width, height = observation["box"]
            results.append(
                {
                    "pose_index": observation["pose_index"],
                    "track_id": track[0] if track else None,
                    "association_confidence": track[1] if track else 0.0,
                    "ambiguous": track is None,
                    "center": observation["center"],
                    "box_norm": [x, y, width, height],
                    "box": [
                        round(x * frame_width),
                        round(y * frame_height),
                        round(width * frame_width),
                        round(height * frame_height),
                    ],
                    "landmarks": observation["landmarks"],
                }
            )
        return results

    @staticmethod
    def _features(pose_index: int, landmarks: list[Any]) -> dict[str, Any] | None:
        if len(landmarks) < 25:
            return None
        shoulder_indices = (11, 12)
        if not all(_visible(landmarks[index]) for index in shoulder_indices):
            return None
        torso_indices = (11, 12, 23, 24)
        torso = tuple(
            (index, (float(landmarks[index].x), float(landmarks[index].y)))
            for index in torso_indices
            if _visible(landmarks[index])
        )
        shoulders = dict(torso)
        center = (
            (shoulders[11][0] + shoulders[12][0]) / 2,
            (shoulders[11][1] + shoulders[12][1]) / 2,
        )
        visible_points = [(float(point.x), float(point.y)) for point in landmarks if _visible(point)]
        if len(visible_points) < 4:
            return None
        left = max(0.0, min(point[0] for point in visible_points) - 0.025)
        top = max(0.0, min(point[1] for point in visible_points) - 0.025)
        right = min(1.0, max(point[0] for point in visible_points) + 0.025)
        bottom = min(1.0, max(point[1] for point in visible_points) + 0.025)
        return {
            "pose_index": pose_index,
            "landmarks": landmarks,
            "center": center,
            "box": (left, top, max(0.01, right - left), max(0.01, bottom - top)),
            "torso": torso,
        }

    @staticmethod
    def _cost(track: _Track, observation: dict[str, Any]) -> float:
        scale = max(0.08, min(0.35, max(track.box[2], track.box[3], observation["box"][2], observation["box"][3])))
        center_cost = _distance(track.center, observation["center"]) / scale
        old_torso = dict(track.torso)
        new_torso = dict(observation["torso"])
        shared = old_torso.keys() & new_torso.keys()
        torso_cost = (
            sum(_distance(old_torso[index], new_torso[index]) for index in shared) / (len(shared) * scale)
            if shared
            else center_cost
        )
        overlap_cost = 1.0 - _iou(track.box, observation["box"])
        return 0.55 * center_cost + 0.35 * torso_cost + 0.10 * overlap_cost

    def active_track_ids(self) -> set[str]:
        return set(self._tracks)
