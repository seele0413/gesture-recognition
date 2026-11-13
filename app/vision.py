from __future__ import annotations

import math
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from app.control import GESTURES, GestureGate, build_controller_event, build_gesture_event
from app.controller import ControllerLock, analyze_v_gesture
from app.pointer import HandPointerController
from app.database import ControlStore
from app.settings import MAX_INFERENCE_WIDTH, MODEL_DIR, MODEL_FILES
from app.tracking import PoseTrackManager


class ModelsMissingError(RuntimeError):
    pass


class VisionProcessor:
    """Processes a stream with session-local pose tracks and gesture control."""

    DEFAULT_MAX_INFERENCE_WIDTH = MAX_INFERENCE_WIDTH
    DEFAULT_LOCK_ACQUISITION_WIDTH = 1600
    DEFAULT_NUM_POSES = 5
    DEFAULT_NUM_HANDS = 10

    def __init__(
        self,
        store: ControlStore,
        publish: Callable[[dict[str, Any]], None],
        models_dir: Path = MODEL_DIR,
        session_id: str = "",
        max_inference_width: int = DEFAULT_MAX_INFERENCE_WIDTH,
        num_poses: int = DEFAULT_NUM_POSES,
        num_hands: int = DEFAULT_NUM_HANDS,
        lock_acquisition_width: int = DEFAULT_LOCK_ACQUISITION_WIDTH,
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
        self.max_inference_width = max(1, int(max_inference_width))
        self.lock_acquisition_width = max(
            self.max_inference_width, int(lock_acquisition_width)
        )
        self.num_poses = max(1, int(num_poses))
        self.num_hands = max(1, int(num_hands))
        self.model_temp_dir: Path | None = None
        self.lock = threading.RLock()
        self.frame_index = 0
        self.track_manager = PoseTrackManager()
        self.controller = ControllerLock()
        self.gate = GestureGate(confidence_threshold=store.get_gesture_confidence_threshold())
        self.pointer = HandPointerController()
        self.pointer_mode_enabled = False
        self.low_confidence_result_count = 0
        self.last_timestamp_ms = 0

        runtime_models = self._runtime_model_paths(models_dir)
        try:
            vision = mp.tasks.vision
            self.gesture_recognizer = vision.GestureRecognizer.create_from_options(
                vision.GestureRecognizerOptions(
                    base_options=mp.tasks.BaseOptions(model_asset_path=runtime_models["gesture"]),
                    running_mode=vision.RunningMode.VIDEO,
                    num_hands=self.num_hands,
                    min_hand_detection_confidence=0.40,
                    min_hand_presence_confidence=0.40,
                    min_tracking_confidence=0.40,
                )
            )
            self.pose_landmarker = vision.PoseLandmarker.create_from_options(
                vision.PoseLandmarkerOptions(
                    base_options=mp.tasks.BaseOptions(model_asset_path=runtime_models["pose"]),
                    running_mode=vision.RunningMode.VIDEO,
                    num_poses=self.num_poses,
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

    def process(self, frame: Any, frame_resize_ms: float = 0.0) -> dict[str, Any]:
        full_started = time.perf_counter()
        preprocessing_started = full_started
        self.frame_index += 1
        source_frame = frame
        source_height, source_width = source_frame.shape[:2]

        # Keep pose tracking at the normal inference size. While no controller is
        # locked, give the hand recognizer a larger image so distant V signs retain
        # more pixels; after lock, return to the normal size to protect latency.
        pose_frame = source_frame
        if source_width > self.max_inference_width:
            pose_scale = self.max_inference_width / source_width
            pose_frame = self.cv2.resize(
                source_frame,
                (self.max_inference_width, max(1, round(source_height * pose_scale))),
            )
        height, width = pose_frame.shape[:2]

        controller_state = self.controller.snapshot()["state"]
        gesture_max_width = (
            max(self.max_inference_width, getattr(self, "lock_acquisition_width", self.max_inference_width))
            if controller_state == "unlocked"
            else self.max_inference_width
        )
        gesture_frame = source_frame
        if source_width > gesture_max_width:
            gesture_scale = gesture_max_width / source_width
            gesture_frame = self.cv2.resize(
                source_frame,
                (gesture_max_width, max(1, round(source_height * gesture_scale))),
            )

        pose_rgb = self.cv2.cvtColor(pose_frame, self.cv2.COLOR_BGR2RGB)
        gesture_rgb = self.cv2.cvtColor(gesture_frame, self.cv2.COLOR_BGR2RGB)
        pose_image = self.mp.Image(
            image_format=self.mp.ImageFormat.SRGB,
            data=self._numpy.ascontiguousarray(pose_rgb),
        )
        gesture_image = self.mp.Image(
            image_format=self.mp.ImageFormat.SRGB,
            data=self._numpy.ascontiguousarray(gesture_rgb),
        )
        frame = pose_frame
        preprocessing_ms = frame_resize_ms + (time.perf_counter() - preprocessing_started) * 1000
        timestamp_ms = max(int(time.monotonic() * 1000), self.last_timestamp_ms + 1)
        self.last_timestamp_ms = timestamp_ms
        pose_started = time.perf_counter()
        poses_result = self.pose_landmarker.detect_for_video(pose_image, timestamp_ms)
        pose_inference_ms = (time.perf_counter() - pose_started) * 1000
        gesture_started = time.perf_counter()
        gestures_result = self.gesture_recognizer.recognize_for_video(gesture_image, timestamp_ms)
        gesture_inference_ms = (time.perf_counter() - gesture_started) * 1000
        tracking_started = time.perf_counter()
        tracks = self.track_manager.update(poses_result.pose_landmarks, width, height, timestamp_ms)
        tracking_ms = (time.perf_counter() - tracking_started) * 1000
        visible_track_ids = {
            track["track_id"]
            for track in tracks
            if track["track_id"] is not None and not track["ambiguous"]
        }
        with self.lock:
            hand_association_started = time.perf_counter()
            hands = self._describe_hands(gestures_result, tracks, self.gate.confidence_threshold)
            hand_association_ms = (time.perf_counter() - hand_association_started) * 1000
            low_confidence_count = sum(
                hand["gesture"] in GESTURES and hand["confidence"] < hand["confidence_threshold"]
                for hand in hands
            )
            self.low_confidence_result_count += low_confidence_count
            lock_candidates: list[str | None] = []
            for hand in hands:
                if not hand["is_lock_gesture"]:
                    continue
                lock_track_id = hand["track_id"]
                if lock_track_id is None:
                    lock_track_id, lock_association_reason = self._associate_hand(
                        hand["landmarks"],
                        tracks,
                        max_distance=0.24,
                        ambiguity_margin=0.04,
                        person_extent_factor=0.42,
                        min_distance=0.12,
                    )
                    hand["lock_association_reason"] = lock_association_reason
                else:
                    hand["lock_association_reason"] = hand["association_reason"]
                hand["lock_track_id"] = lock_track_id
                lock_candidates.append(lock_track_id)
            lock_result = self.controller.observe_lock_candidates(lock_candidates, timestamp_ms)
            if lock_result == "locked":
                self.gate.reset(preserve_cooldowns=True)
                self._publish_controller("locked", "v_gesture", timestamp_ms)

            transitions = self.controller.update_tracking(visible_track_ids, timestamp_ms, tracks=tracks)
            if transitions:
                self.gate.reset(preserve_cooldowns=True)
                for state, reason in transitions:
                    self._publish_controller(state, reason, timestamp_ms)

            control_started = time.perf_counter()
            events = self._process_controller_hands(hands, timestamp_ms)
            controller = self.controller.snapshot()
            pointer_hands = (
                self._pointer_hands(hands, tracks, controller["track_id"])
                if self.pointer_mode_enabled
                else hands
            )
            pointer_event = self.pointer.update(
                pointer_hands, controller["state"], controller["track_id"], timestamp_ms
            )
            if pointer_event:
                self.publish(pointer_event)
            control_ms = (time.perf_counter() - control_started) * 1000
            hand_diagnostics = [self._public_hand(hand) for hand in hands]
        diagnostics = {
            "hand_count": len(hands),
            "pose_inference_width": width,
            "hand_inference_width": int(gesture_frame.shape[1]),
            "lock_gesture_count": sum(hand["is_lock_gesture"] for hand in hands),
            "associated_hand_count": sum(hand["track_id"] is not None for hand in hands),
            "associated_lock_gesture_count": sum(
                hand["is_lock_gesture"] and hand.get("lock_track_id") is not None
                for hand in hands
            ),
            "hands": hand_diagnostics,
            "lock_progress": controller["lock_progress"],
            "last_gesture": hand_diagnostics[0] if hand_diagnostics else None,
            "confidence_threshold": self.gate.confidence_threshold,
            "low_confidence_hand_count": low_confidence_count,
            "low_confidence_result_count": self.low_confidence_result_count,
        }
        public_tracks = [self._public_track(track) for track in tracks]
        diagnostics["timings"] = {
            "preprocessing_ms": round(preprocessing_ms, 2),
            "pose_inference_ms": round(pose_inference_ms, 2),
            "gesture_inference_ms": round(gesture_inference_ms, 2),
            "tracking_ms": round(tracking_ms, 2),
            "hand_association_ms": round(hand_association_ms, 2),
            "control_ms": round(control_ms, 2),
            "full_vision_ms": round((time.perf_counter() - full_started) * 1000 + frame_resize_ms, 2),
        }
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

    def _describe_hands(
        self,
        result: Any,
        tracks: list[dict[str, Any]],
        confidence_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        threshold = self.gate.confidence_threshold if confidence_threshold is None else confidence_threshold
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
            lock_geometry = analyze_v_gesture(landmarks)
            hands.append(
                {
                    "landmarks": landmarks,
                    "track_id": track_id,
                    "association_reason": association_reason,
                    "handedness": handedness,
                    "gesture": label,
                    "confidence": confidence,
                    "confidence_threshold": threshold,
                    "is_lock_gesture": lock_geometry["is_v"],
                    "lock_gesture_reason": lock_geometry["reason"],
                    "lock_spread_ratio": lock_geometry["spread_ratio"],
                    "lock_association_reason": association_reason,
                    "action": "none",
                    "action_reason": "等待主控锁定",
                    "reason_code": "waiting",
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
        landmarks: list[Any],
        tracks: list[dict[str, Any]],
        max_distance: float = 0.16,
        ambiguity_margin: float = 0.025,
        person_extent_factor: float = 0.26,
        min_distance: float = 0.08,
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
            box = track.get("box_norm")
            distance_limit = max_distance
            if box and len(box) == 4:
                person_extent = max(float(box[2]), float(box[3]))
                distance_limit = min(max_distance, max(min_distance, person_extent * person_extent_factor))
            for wrist_index in (15, 16):
                pose_wrist = pose[wrist_index]
                if not VisionProcessor._landmark_visible(pose_wrist):
                    continue
                distance = math.hypot(float(wrist.x) - float(pose_wrist.x), float(wrist.y) - float(pose_wrist.y))
                if distance <= distance_limit:
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
    def _pointer_hands(
        hands: list[dict[str, Any]],
        tracks: list[dict[str, Any]],
        controller_track_id: str | None,
    ) -> list[dict[str, Any]]:
        """Use a slightly wider, ambiguity-checked wrist match for pointer-only input."""
        if not controller_track_id:
            return hands
        pointer_hands = []
        for hand in hands:
            if hand.get("track_id") is not None or hand.get("is_lock_gesture"):
                pointer_hands.append(hand)
                continue
            track_id, _reason = VisionProcessor._associate_hand(
                hand.get("landmarks") or [],
                tracks,
                max_distance=0.24,
                ambiguity_margin=0.04,
                person_extent_factor=0.42,
                min_distance=0.12,
            )
            if track_id == controller_track_id:
                pointer_hand = dict(hand)
                pointer_hand["track_id"] = track_id
                pointer_hands.append(pointer_hand)
            else:
                pointer_hands.append(hand)
        return pointer_hands

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
            "box_norm": list(track["box_norm"]),
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
            "is_lock_gesture": hand["is_lock_gesture"],
            "lock_gesture_reason": hand["lock_gesture_reason"],
            "lock_spread_ratio": hand["lock_spread_ratio"],
            "lock_association_reason": hand.get("lock_association_reason", hand["association_reason"]),
            "lock_track_id": hand.get("lock_track_id"),
            "action": hand["action"],
            "action_reason": hand["action_reason"],
            "reason_code": hand["reason_code"],
            "confidence_threshold": hand["confidence_threshold"],
            "stable_frames": hand["stable_frames"],
            "landmarks": [
                {"x": float(point.x), "y": float(point.y)}
                for point in hand["landmarks"]
            ],
        }

    def _publish_controller(self, state: str, reason: str, timestamp_ms: int) -> None:
        controller_snapshot = self.controller.snapshot()
        controller_event = build_controller_event(
            state=state,
            track_id=controller_snapshot["track_id"],
            controller_id=controller_snapshot["controller_id"],
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
            pointer_event = self.pointer.reset(self.last_timestamp_ms)
            if pointer_event:
                self.publish(pointer_event)
            if changed:
                self._publish_controller("unlocked", "manual", self.last_timestamp_ms)
            return self.controller.snapshot()

    def set_confidence_threshold(self, threshold: float) -> float:
        with self.lock:
            self.gate.set_confidence_threshold(threshold)
            return self.gate.confidence_threshold

    def set_pointer_mode(self, enabled: bool) -> bool:
        with self.lock:
            self.pointer_mode_enabled = bool(enabled)
            self.gate.reset(preserve_cooldowns=True)
            pointer_event = self.pointer.set_enabled(self.pointer_mode_enabled, self.last_timestamp_ms)
            if pointer_event:
                self.publish(pointer_event)
            return self.pointer_mode_enabled

    def _process_controller_hands(self, hands: list[dict[str, Any]], timestamp_ms: int) -> list[dict[str, Any]]:
        controller = self.controller.snapshot()
        track_id = controller["track_id"]
        if controller["state"] != "locked" or not track_id:
            self.gate.reset()
            for hand in hands:
                if controller["state"] in {"suspect", "reacquiring", "lost"}:
                    hand["action_reason"] = (
                        "主控轨迹暂时不可见，正在等待恢复" 
                        if controller["state"] == "suspect"
                        else "正在重新寻找原主控，控制已暂停"
                    )
                    hand["reason_code"] = "master_track_reacquiring"
                elif hand["is_lock_gesture"] and hand.get("lock_track_id"):
                    hand["action_reason"] = (
                        f"比耶手势已识别，锁定进度 "
                        f"{controller['lock_progress']}/{controller['lock_required_frames']} "
                        f"（最近 {controller['lock_window_frames']} 帧）"
                    )
                    hand["reason_code"] = "locking_controller"
                elif hand["is_lock_gesture"]:
                    hand["action_reason"] = hand.get("lock_association_reason", hand["association_reason"])
                    hand["reason_code"] = "hand_not_associated"
                else:
                    if hand["gesture"] not in GESTURES:
                        hand["action_reason"] = "未识别到内置手势"
                        hand["reason_code"] = "unrecognized_gesture"
                    elif hand["confidence"] < hand["confidence_threshold"]:
                        hand["action_reason"] = (
                            f"识别置信度不足（{hand['confidence']:.0%}，"
                            f"门槛 {hand['confidence_threshold']:.0%}）"
                        )
                        hand["reason_code"] = "low_confidence"
                    else:
                        hand["action_reason"] = "比耶手势未确认：" + hand["lock_gesture_reason"]
                        hand["reason_code"] = "waiting_for_controller_lock"
            return []

        if self.pointer_mode_enabled:
            self.gate.reset()
            for hand in hands:
                if hand["track_id"] == track_id:
                    hand["action_reason"] = "手势指针模式已启用，普通手势映射暂时暂停"
                    hand["reason_code"] = "pointer_mode"
            return []

        mappings = self.store.get_mappings()
        active_keys: set[str] = set()
        events = []
        for hand in hands:
            if hand["track_id"] != track_id:
                hand["action_reason"] = "手未关联到当前主控人"
                hand["reason_code"] = "hand_not_associated"
                continue
            if hand["is_lock_gesture"] or hand["gesture"] == "Victory":
                hand["action_reason"] = "比耶手势保留用于主控锁定，不执行普通网页动作"
                hand["reason_code"] = "controller_lock_gesture"
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
            hand["reason_code"] = gate_status["reason_code"]
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
