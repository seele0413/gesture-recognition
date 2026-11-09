from __future__ import annotations

import math
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from app.control import GestureGate, build_controller_event, build_gesture_event
from app.controller import ControllerLock, analyze_ok_gesture
from app.database import ControlStore
from app.settings import MODEL_DIR, MODEL_FILES
from app.tracking import PoseTrackManager


class ModelsMissingError(RuntimeError):
    pass


class VisionProcessor:
    """Processes a stream with session-local pose tracks and gesture control."""

    def __init__(
        self,
        store: ControlStore,
        publish: Callable[[dict[str, Any]], None],
        models_dir: Path = MODEL_DIR,
        session_id: str = "",
    ):
        missing = [name for name in MODEL_FILES.values() if not (models_dir / name).is_file()]
        if missing:
            raise ModelsMissingError("缺少识别模型，请先运行 setup.ps1 下载模型。")

        import cv2
        import mediapipe as mp

        self.cv2 = cv2
        self.mp = mp
        self.store = store
        self.publish = publish
        self.session_id = session_id
        self.model_temp_dir: Path | None = None
        self.lock = threading.RLock()
        self.frame_index = 0
        self.track_manager = PoseTrackManager()
        self.controller = ControllerLock()
        self.gate = GestureGate()
        self.last_timestamp_ms = 0

        runtime_models = self._runtime_model_paths(models_dir)
        try:
            vision = mp.tasks.vision
            self.gesture_recognizer = vision.GestureRecognizer.create_from_options(
                vision.GestureRecognizerOptions(
                    base_options=mp.tasks.BaseOptions(model_asset_path=runtime_models["gesture"]),
                    running_mode=vision.RunningMode.VIDEO,
                    num_hands=10,
                    min_hand_detection_confidence=0.45,
                    min_hand_presence_confidence=0.45,
                    min_tracking_confidence=0.45,
                )
            )
            self.pose_landmarker = vision.PoseLandmarker.create_from_options(
                vision.PoseLandmarkerOptions(
                    base_options=mp.tasks.BaseOptions(model_asset_path=runtime_models["pose"]),
                    running_mode=vision.RunningMode.VIDEO,
                    num_poses=5,
                    min_pose_detection_confidence=0.45,
                    min_pose_presence_confidence=0.45,
                    min_tracking_confidence=0.45,
                    output_segmentation_masks=False,
                )
            )
        except Exception:
            self.close()
            raise

    def _runtime_model_paths(self, models_dir: Path) -> dict[str, str]:
        paths = {key: (models_dir / filename).resolve() for key, filename in MODEL_FILES.items()}
        if os.name != "nt" or all(str(path).isascii() for path in paths.values()):
            return {key: str(path) for key, path in paths.items()}

        import ctypes

        get_short_path = ctypes.windll.kernel32.GetShortPathNameW
        get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        get_short_path.restype = ctypes.c_uint
        short_paths = {}
        for key, path in paths.items():
            buffer = ctypes.create_unicode_buffer(32768)
            length = get_short_path(str(path), buffer, len(buffer))
            short_paths[key] = buffer.value if length and length < len(buffer) else str(path)
        if all(path.isascii() for path in short_paths.values()):
            return short_paths

        windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        temp_roots = (windows_root / "Temp", Path("C:/Temp"), Path(tempfile.gettempdir()))
        for root in temp_roots:
            if not root.is_dir() or not str(root).isascii():
                continue
            try:
                self.model_temp_dir = Path(tempfile.mkdtemp(prefix="rtsp-gesture-", dir=root))
                staged = {}
                for key, path in paths.items():
                    destination = self.model_temp_dir / path.name
                    shutil.copyfile(path, destination)
                    staged[key] = str(destination)
                return staged
            except OSError:
                if self.model_temp_dir:
                    shutil.rmtree(self.model_temp_dir, ignore_errors=True)
                    self.model_temp_dir = None
        raise RuntimeError(
            "Vision models cannot load from this Unicode path. Enable short Windows paths or install under an ASCII path."
        )

    def process(self, frame: Any) -> dict[str, Any]:
        self.frame_index += 1
        height, width = frame.shape[:2]
        if width > 960:
            scale = 960 / width
            frame = self.cv2.resize(frame, (960, max(1, round(height * scale))))
            height, width = frame.shape[:2]

        rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
        image = self.mp.Image(
            image_format=self.mp.ImageFormat.SRGB,
            data=self._numpy.ascontiguousarray(rgb),
        )
        timestamp_ms = max(int(time.monotonic() * 1000), self.last_timestamp_ms + 1)
        self.last_timestamp_ms = timestamp_ms
        poses_result = self.pose_landmarker.detect_for_video(image, timestamp_ms)
        gestures_result = self.gesture_recognizer.recognize_for_video(image, timestamp_ms)
        tracks = self.track_manager.update(poses_result.pose_landmarks, width, height, timestamp_ms)
        hands = self._describe_hands(gestures_result, tracks)

        visible_track_ids = {
            track["track_id"]
            for track in tracks
            if track["track_id"] is not None and not track["ambiguous"]
        }
        with self.lock:
            lock_candidates = [hand["track_id"] for hand in hands if hand["is_ok"]]
            lock_result = self.controller.observe_lock_candidates(lock_candidates, timestamp_ms)
            if lock_result == "locked":
                self.gate.reset(preserve_cooldowns=True)
                self._publish_controller("locked", "ok_gesture", timestamp_ms)

            transitions = self.controller.update_tracking(visible_track_ids, timestamp_ms)
            if transitions:
                self.gate.reset(preserve_cooldowns=True)
                for state, reason in transitions:
                    self._publish_controller(state, reason, timestamp_ms)

            events = self._process_controller_hands(hands, timestamp_ms)
            controller = self.controller.snapshot()
            hand_diagnostics = [self._public_hand(hand) for hand in hands]
        diagnostics = {
            "hand_count": len(hands),
            "ok_hand_count": sum(hand["is_ok"] for hand in hands),
            "associated_hand_count": sum(hand["track_id"] is not None for hand in hands),
            "associated_ok_count": sum(hand["is_ok"] and hand["track_id"] is not None for hand in hands),
            "hands": hand_diagnostics,
            "lock_progress": controller["lock_progress"],
            "last_gesture": hand_diagnostics[0] if hand_diagnostics else None,
        }
        public_tracks = [self._public_track(track) for track in tracks]
        return {
            "frame": frame,
            "frame_width": width,
            "frame_height": height,
            "tracks": public_tracks,
            "controller": controller,
            "vision": diagnostics,
            "events": events,
        }

    @property
    def _numpy(self) -> Any:
        import numpy

        return numpy

    def _describe_hands(self, result: Any, tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        hands = []
        for hand_index, landmarks in enumerate(result.hand_landmarks):
            categories = result.gestures[hand_index] if hand_index < len(result.gestures) else []
            category = categories[0] if categories else None
            handedness_categories = result.handedness[hand_index] if hand_index < len(result.handedness) else []
            handedness = handedness_categories[0].category_name if handedness_categories else "Unknown"
            label = category.category_name if category else None
            if label == "None":
                label = None
            confidence = float(category.score) if category else 0.0
            track_id, association_reason = self._associate_hand(landmarks, tracks)
            ok_geometry = analyze_ok_gesture(landmarks)
            hands.append(
                {
                    "landmarks": landmarks,
                    "track_id": track_id,
                    "association_reason": association_reason,
                    "handedness": handedness,
                    "gesture": label,
                    "confidence": confidence,
                    "is_ok": ok_geometry["is_ok"],
                    "ok_reason": ok_geometry["reason"],
                    "tip_ratio": ok_geometry["tip_ratio"],
                    "action": "none",
                    "action_reason": "等待主控锁定",
                    "stable_frames": 0,
                }
            )
        return hands

    @staticmethod
    def _associate_hand_to_track(
        landmarks: list[Any], tracks: list[dict[str, Any]], max_distance: float = 0.16, ambiguity_margin: float = 0.025
    ) -> str | None:
        return VisionProcessor._associate_hand(landmarks, tracks, max_distance, ambiguity_margin)[0]

    @staticmethod
    def _associate_hand(
        landmarks: list[Any], tracks: list[dict[str, Any]], max_distance: float = 0.16, ambiguity_margin: float = 0.025
    ) -> tuple[str | None, str]:
        if not landmarks:
            return None, "缺少手部关键点"
        wrist = landmarks[0]
        best_by_track: dict[str, float] = {}
        for track in tracks:
            track_id = track["track_id"]
            pose = track["landmarks"]
            if track_id is None or track["ambiguous"]:
                continue
            if len(pose) <= 16:
                continue
            for wrist_index in (15, 16):
                pose_wrist = pose[wrist_index]
                if not VisionProcessor._landmark_visible(pose_wrist):
                    continue
                distance = math.hypot(float(wrist.x) - float(pose_wrist.x), float(wrist.y) - float(pose_wrist.y))
                if distance <= max_distance:
                    best_by_track[track_id] = min(distance, best_by_track.get(track_id, float("inf")))
        candidates = sorted((distance, track_id) for track_id, distance in best_by_track.items())
        if candidates:
            if len(candidates) == 1 or candidates[1][0] - candidates[0][0] >= ambiguity_margin:
                return candidates[0][1], "与人体手腕唯一匹配"
            return None, "多人手腕关联有歧义"

        center_x = sum(float(point.x) for point in landmarks) / len(landmarks)
        center_y = sum(float(point.y) for point in landmarks) / len(landmarks)
        box_matches = []
        for track in tracks:
            track_id = track["track_id"]
            box = track.get("box_norm")
            if track_id is None or track["ambiguous"] or not box:
                continue
            left, top, box_width, box_height = box
            if left <= center_x <= left + box_width and top <= center_y <= top + box_height:
                box_matches.append(track_id)
        if len(box_matches) == 1:
            return box_matches[0], "手腕不可用，手部区域只落入一个人体框"
        if len(box_matches) > 1:
            return None, "多人手腕或人体框关联有歧义"
        return None, "未能关联到人体手腕或唯一人体框"

    @staticmethod
    def _landmark_visible(landmark: Any) -> bool:
        visibility = getattr(landmark, "visibility", 1.0)
        presence = getattr(landmark, "presence", 1.0)
        return (visibility is None or visibility >= 0.35) and (presence is None or presence >= 0.35)

    @staticmethod
    def _public_track(track: dict[str, Any]) -> dict[str, Any]:
        return {
            "track_id": track["track_id"],
            "box": list(track["box"]),
            "association_confidence": float(track["association_confidence"]),
            "ambiguous": bool(track["ambiguous"]),
        }

    @staticmethod
    def _public_hand(hand: dict[str, Any]) -> dict[str, Any]:
        return {
            "handedness": hand["handedness"],
            "gesture": hand["gesture"],
            "confidence": hand["confidence"],
            "track_id": hand["track_id"],
            "association_reason": hand["association_reason"],
            "is_ok": hand["is_ok"],
            "ok_reason": hand["ok_reason"],
            "tip_ratio": hand["tip_ratio"],
            "action": hand["action"],
            "action_reason": hand["action_reason"],
            "stable_frames": hand["stable_frames"],
            "landmarks": [
                {"x": float(point.x), "y": float(point.y)}
                for point in hand["landmarks"]
            ],
        }

    def _publish_controller(self, state: str, reason: str, timestamp_ms: int) -> None:
        controller_event = build_controller_event(
            state=state,
            track_id=self.controller.track_id,
            timestamp_ms=int(time.time() * 1000),
            reason=reason,
        )
        if self.session_id:
            self.store.update_controller(
                self.session_id,
                state,
                self.controller.track_id,
                int(time.time() * 1000),
            )
        self.publish(controller_event)

    def unlock_controller(self) -> dict[str, Any]:
        with self.lock:
            changed = self.controller.unlock()
            self.gate.reset(preserve_cooldowns=True)
            if changed:
                self._publish_controller("unlocked", "manual", self.last_timestamp_ms)
            return self.controller.snapshot()

    def _process_controller_hands(self, hands: list[dict[str, Any]], timestamp_ms: int) -> list[dict[str, Any]]:
        controller = self.controller.snapshot()
        track_id = controller["track_id"]
        if controller["state"] != "locked" or not track_id:
            self.gate.reset()
            for hand in hands:
                if controller["state"] == "lost":
                    hand["action_reason"] = "主控轨迹暂时丢失，控制已暂停"
                elif hand["is_ok"] and hand["track_id"]:
                    hand["action_reason"] = (
                        f"OK 已确认，锁定进度 {controller['lock_progress']}/"
                        f"{controller['lock_required_frames']} 帧"
                    )
                elif hand["is_ok"]:
                    hand["action_reason"] = hand["association_reason"]
                else:
                    hand["action_reason"] = "OK 未确认：" + hand["ok_reason"]
            return []

        mappings = self.store.get_mappings()
        active_keys: set[str] = set()
        events = []
        for hand in hands:
            if hand["track_id"] != track_id:
                hand["action_reason"] = "手未关联到当前主控人"
                continue
            if hand["is_ok"]:
                hand["action_reason"] = "OK 仅用于锁定主控，不执行网页动作"
                continue
            handedness = hand["handedness"]
            gesture = hand["gesture"]
            confidence = hand["confidence"]
            action = mappings.get(gesture, "none") if gesture else "none"
            hand["action"] = action
            key = f"{track_id}:{handedness}"
            active_keys.add(key)
            action_triggered = self.gate.observe(key, gesture, confidence, action, timestamp_ms)
            gate_status = self.gate.status(key)
            hand["action_reason"] = gate_status["reason"]
            hand["stable_frames"] = gate_status["stable_frames"]
            if action_triggered is None:
                continue
            event = build_gesture_event(
                target_id=track_id,
                target_name="主控人",
                gesture=gesture,
                confidence=confidence,
                handedness=handedness,
                timestamp_ms=int(time.time() * 1000),
                action=action,
                action_triggered=action_triggered,
                landmarks=[
                    {"x": float(point.x), "y": float(point.y), "z": float(point.z)}
                    for point in hand["landmarks"]
                ],
            )
            if self.session_id:
                self.store.record_gesture(self.session_id, event)
            events.append(event)
            self.publish(event)

        self.gate.reset_except(active_keys)
        return events

    def close(self) -> None:
        if hasattr(self, "gesture_recognizer"):
            self.gesture_recognizer.close()
        if hasattr(self, "pose_landmarker"):
            self.pose_landmarker.close()
        if self.model_temp_dir:
            shutil.rmtree(self.model_temp_dir, ignore_errors=True)
            self.model_temp_dir = None
