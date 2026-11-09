import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np
import sqlite3

from app.database import ControlStore
from app.events import EventHub
from app.stream import StreamManager, _LatestFrameReader
from app.decoder import PyAVDecoder


class FakeCapture:
    def __init__(self):
        self.closed = threading.Event()
        self.frame = np.zeros((32, 48, 3), dtype=np.uint8)

    def isOpened(self):
        return True

    def set(self, *_args):
        return True

    def read(self):
        if self.closed.wait(0.01):
            return False, None
        return True, self.frame.copy()

    def release(self):
        self.closed.set()


class DisconnectAfterOneFrame:
    def __init__(self):
        self.frame = np.zeros((32, 48, 3), dtype=np.uint8)
        self.read_count = 0
        self.closed = False

    def read(self):
        self.read_count += 1
        if self.closed or self.read_count > 1:
            return False, None
        return True, self.frame.copy()

    def close(self):
        self.closed = True


class BurstDecoder:
    def __init__(self, frame_count=100):
        self.frame_count = frame_count
        self.index = 0

    def read(self):
        if self.index >= self.frame_count:
            return False, None
        frame = np.full((4, 4, 3), self.index, dtype=np.uint8)
        self.index += 1
        return True, frame


class FakeProcessor:
    def __init__(self, _store, _publish, _models_dir, _session_id):
        self.controller = type("Controller", (), {"snapshot": lambda _self: {"state": "unlocked", "track_id": None}})()

    def unlock_controller(self):
        return {"state": "unlocked", "track_id": None}

    def process(self, frame):
        height, width = frame.shape[:2]
        return {
            "frame": frame,
            "frame_width": width,
            "frame_height": height,
            "tracks": [],
            "controller": {"state": "unlocked", "track_id": None},
            "events": [],
        }

    def close(self):
        pass


class RecoveringProcessor(FakeProcessor):
    def __init__(self, store, publish, models_dir, session_id):
        super().__init__(store, publish, models_dir, session_id)
        self.failed_once = False

    def process(self, frame):
        if not self.failed_once:
            self.failed_once = True
            raise ValueError("simulated damaged frame")
        return super().process(frame)


class AlwaysFailProcessor(FakeProcessor):
    def process(self, _frame):
        raise ValueError("simulated repeated frame failure")


class StreamManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ControlStore(Path(self.temp_dir.name) / "data.sqlite3")
        self.capture = FakeCapture()
        self.manager = StreamManager(
            self.store,
            EventHub(),
            capture_factory=lambda _url: self.capture,
            processor_factory=FakeProcessor,
        )

    def tearDown(self):
        self.manager.stop()
        self.temp_dir.cleanup()

    def test_latest_frame_reader_discards_backlog_and_keeps_newest_frame(self):
        decoder = BurstDecoder(frame_count=100)
        dropped = []
        reader = _LatestFrameReader(decoder, threading.Event(), lambda: dropped.append(1))
        reader.start()
        self.assertTrue(reader.wait_finished(timeout=2))

        item = reader.read(timeout=0.01)
        self.assertIsNotNone(item)
        frame, _received_at = item
        self.assertEqual(int(frame[0, 0, 0]), 99)
        self.assertEqual(reader.dropped_frames, 99)
        self.assertEqual(len(dropped), 99)
        with self.assertRaisesRegex(RuntimeError, "decoder_read_failed"):
            reader.read(timeout=0.01)
        reader.stop()
        reader.join(timeout=1)

    def test_substitute_stream_runs_without_camera_hardware(self):
        self.manager.start("rtsp://camera.local/live")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = self.manager.get_status()
            if status["state"] == "running" and status["frame_width"]:
                break
            time.sleep(0.02)
        self.assertEqual(status["state"], "running")
        self.assertEqual(status["frame_width"], 48)
        self.assertTrue(status["frame_ready"])
        self.assertTrue(status["frame_fresh"])
        self.assertGreater(status["frame_sequence"], 0)
        self.assertIsNotNone(status["last_frame_at_ms"])
        self.assertIsInstance(status["last_vision_ms"], float)
        self.assertIsInstance(status["last_jpeg_encode_ms"], float)
        self.assertIsInstance(status["last_queue_delay_ms"], float)
        self.assertGreaterEqual(status["dropped_frames"], 0)
        self.assertEqual(status["controller"]["state"], "unlocked")
        self.assertIsNotNone(self.manager.get_jpeg())
        connection = sqlite3.connect(self.store.path)
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM controller_sessions").fetchone()[0], 1)
        finally:
            connection.close()
        self.manager.stop()
        self.assertEqual(self.manager.get_status()["state"], "stopped")
        connection = sqlite3.connect(self.store.path)
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM controller_sessions").fetchone()[0], 0)
        finally:
            connection.close()

    def test_single_processing_error_is_skipped_without_reconnecting(self):
        capture = FakeCapture()
        manager = StreamManager(
            self.store,
            EventHub(),
            capture_factory=lambda _url: capture,
            processor_factory=RecoveringProcessor,
        )
        try:
            manager.start("rtsp://camera.local/live")
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                status = manager.get_status()
                if status["frame_ready"]:
                    break
                time.sleep(0.02)
            self.assertEqual(status["state"], "running")
            self.assertTrue(status["frame_ready"])
            self.assertEqual(status["reconnect_count"], 0)
        finally:
            manager.stop()

    def test_repeated_processing_errors_recreate_the_stream_session(self):
        created_processors = 0

        def processor_factory(store, publish, models_dir, session_id):
            nonlocal created_processors
            created_processors += 1
            processor_type = AlwaysFailProcessor if created_processors == 1 else FakeProcessor
            return processor_type(store, publish, models_dir, session_id)

        manager = StreamManager(
            self.store,
            EventHub(),
            processor_factory=processor_factory,
            decoder_factory=lambda _url: FakeCapture(),
            reconnect_delays=(0.02,),
        )
        try:
            manager.start("rtsp://camera.local/live")
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                status = manager.get_status()
                if created_processors >= 2 and status["frame_ready"]:
                    break
                time.sleep(0.02)
            self.assertGreaterEqual(created_processors, 2)
            self.assertGreaterEqual(status["reconnect_count"], 1)
            self.assertEqual(status["state"], "running")
            self.assertTrue(status["frame_ready"])
        finally:
            manager.stop()

    def test_manual_unlock_route_updates_controller_state(self):
        state = self.manager.unlock_controller()
        self.assertEqual(state["state"], "unlocked")

    def test_invalid_stream_url_is_rejected_before_capture(self):
        with self.assertRaises(ValueError):
            self.manager.start("https://example.com/video")
        self.assertEqual(self.manager.get_status()["state"], "stopped")

    def test_read_failure_reconnects_with_a_fresh_unlocked_session(self):
        sessions = []
        decoders = [DisconnectAfterOneFrame(), FakeCapture()]

        def decoder_factory(_url):
            return decoders.pop(0)

        def processor_factory(store, publish, models_dir, session_id):
            sessions.append(session_id)
            return FakeProcessor(store, publish, models_dir, session_id)

        manager = StreamManager(
            self.store,
            EventHub(),
            capture_factory=None,
            processor_factory=processor_factory,
            decoder_factory=decoder_factory,
            reconnect_delays=(0.02,),
        )
        try:
            manager.start("rtsp://camera.local/live")
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                status = manager.get_status()
                if len(sessions) >= 2 and status["state"] == "running" and status["frame_ready"]:
                    break
                time.sleep(0.01)
            self.assertEqual(len(sessions), 2)
            self.assertNotEqual(sessions[0], sessions[1])
            status = manager.get_status()
            self.assertEqual(status["state"], "running")
            self.assertEqual(status["controller"]["state"], "unlocked")
            self.assertTrue(status["frame_ready"])
            self.assertGreaterEqual(status["reconnect_count"], 1)
        finally:
            manager.stop()

    def test_disconnect_unlocks_a_previously_locked_controller(self):
        sessions = []
        decoders = [DisconnectAfterOneFrame(), FakeCapture()]
        published = []
        hub = EventHub()
        hub.publish_from_thread = published.append

        class LockedProcessor(FakeProcessor):
            def __init__(self, store, publish, models_dir, session_id):
                super().__init__(store, publish, models_dir, session_id)
                self.controller.snapshot = lambda: {"state": "locked", "track_id": "person-1"}

            def process(self, frame):
                result = super().process(frame)
                result["controller"] = {"state": "locked", "track_id": "person-1"}
                return result

        def decoder_factory(_url):
            return decoders.pop(0)

        def processor_factory(store, publish, models_dir, session_id):
            sessions.append(session_id)
            return LockedProcessor(store, publish, models_dir, session_id) if len(sessions) == 1 else FakeProcessor(
                store, publish, models_dir, session_id
            )

        manager = StreamManager(
            self.store,
            hub,
            processor_factory=processor_factory,
            decoder_factory=decoder_factory,
            reconnect_delays=(0.02,),
        )
        try:
            manager.start("rtsp://camera.local/live")
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                status = manager.get_status()
                if len(sessions) >= 2 and status["state"] == "running" and status["frame_ready"]:
                    break
                time.sleep(0.01)
            self.assertEqual(len(sessions), 2)
            self.assertNotEqual(sessions[0], sessions[1])
            self.assertEqual(manager.get_status()["controller"]["state"], "unlocked")
            self.assertTrue(
                any(event.get("type") == "controller" and event.get("reason") == "stream_reconnected" for event in published)
            )
        finally:
            manager.stop()

    def test_failed_decoder_retries_without_exposing_rtsp_credentials_and_stop_cancels_retry(self):
        address = "rtsp://operator:s3cret@camera.local/live"
        calls = []

        def decoder_factory(url):
            calls.append(url)
            raise RuntimeError(url)

        manager = StreamManager(
            self.store,
            EventHub(),
            processor_factory=FakeProcessor,
            decoder_factory=decoder_factory,
            reconnect_delays=(0.5,),
        )
        try:
            manager.start(address)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and manager.get_status()["state"] != "reconnecting":
                time.sleep(0.01)
            status = manager.get_status()
            self.assertEqual(status["state"], "reconnecting")
            self.assertEqual(status["reconnect_count"], 1)
            self.assertNotIn("operator", status["error"])
            self.assertNotIn("s3cret", status["error"])
            self.assertEqual(status["reconnect_attempt"], 1)
            manager.stop()
            time.sleep(0.55)
            self.assertEqual(len(calls), 1)
        finally:
            manager.stop()


if __name__ == "__main__":
    unittest.main()
