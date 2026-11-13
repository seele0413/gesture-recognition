import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from app.control import GestureGate
from app.controller import ControllerLock
from app.database import ControlStore
from app.tracking import PoseTrackManager
from app.pointer import HandPointerController
from app.vision import VisionProcessor


class _PoseLandmarker:
    def __init__(self):
        self.last_image_shape = None

    def detect_for_video(self, image, _timestamp_ms):
        self.last_image_shape = image.data.shape
        return SimpleNamespace(pose_landmarks=[])


class _GestureRecognizer:
    def __init__(self):
        self.last_image_shape = None

    def recognize_for_video(self, image, _timestamp_ms):
        self.last_image_shape = image.data.shape
        return SimpleNamespace(hand_landmarks=[], gestures=[], handedness=[])


class VisionTimingTests(unittest.TestCase):
    def test_process_uses_high_res_hand_search_before_lock_and_reports_timings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            processor = VisionProcessor.__new__(VisionProcessor)
            processor.cv2 = cv2
            processor.mp = SimpleNamespace(
                Image=lambda **kwargs: SimpleNamespace(**kwargs),
                ImageFormat=SimpleNamespace(SRGB=1),
            )
            processor.store = ControlStore(Path(temp_dir) / "data.sqlite3")
            processor.publish = lambda _event: None
            processor.session_id = ""
            processor.lock = threading.RLock()
            processor.frame_index = 0
            processor.max_inference_width = 960
            processor.lock_acquisition_width = 1280
            processor.track_manager = PoseTrackManager()
            processor.controller = ControllerLock()
            processor.gate = GestureGate()
            processor.pointer = HandPointerController()
            processor.pointer_mode_enabled = False
            processor.low_confidence_result_count = 0
            processor.last_timestamp_ms = 0
            processor.pose_landmarker = _PoseLandmarker()
            processor.gesture_recognizer = _GestureRecognizer()

            result = processor.process(np.zeros((1080, 1920, 3), dtype=np.uint8), frame_resize_ms=0.25)

        self.assertEqual((result["frame_width"], result["frame_height"]), (960, 540))
        self.assertEqual(processor.pose_landmarker.last_image_shape, (540, 960, 3))
        self.assertEqual(processor.gesture_recognizer.last_image_shape, (900, 1600, 3))
        timings = result["vision"]["timings"]
        for name in (
            "preprocessing_ms",
            "pose_inference_ms",
            "gesture_inference_ms",
            "tracking_ms",
            "hand_association_ms",
            "control_ms",
            "full_vision_ms",
        ):
            self.assertGreaterEqual(timings[name], 0.0)
        self.assertGreaterEqual(timings["preprocessing_ms"], 0.25)
        measured_stages = sum(
            timings[name]
            for name in (
                "preprocessing_ms",
                "pose_inference_ms",
                "gesture_inference_ms",
                "tracking_ms",
                "hand_association_ms",
                "control_ms",
            )
        )
        self.assertGreaterEqual(timings["full_vision_ms"] + 0.05, measured_stages)


if __name__ == "__main__":
    unittest.main()
