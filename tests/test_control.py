import unittest

from app.control import (
    ACTIONS,
    DEFAULT_MAPPINGS,
    GestureGate,
    build_controller_event,
    build_gesture_event,
    validate_mappings,
    validate_rtsp_url,
)


class ControlTests(unittest.TestCase):
    def test_gesture_requires_three_stable_frames_and_emits_once(self):
        gate = GestureGate(stable_frames=3, confidence_threshold=0.7, cooldown_ms=800)
        self.assertIsNone(gate.observe("target:Left", "Thumb_Up", 0.9, "volume_up", 1000))
        self.assertIsNone(gate.observe("target:Left", "Thumb_Up", 0.9, "volume_up", 1033))
        self.assertIn("2/3", gate.status("target:Left")["reason"])
        self.assertTrue(gate.observe("target:Left", "Thumb_Up", 0.9, "volume_up", 1066))
        self.assertEqual(gate.status("target:Left")["reason"], "动作已触发")
        self.assertIsNone(gate.observe("target:Left", "Thumb_Up", 0.95, "volume_up", 1099))

    def test_low_confidence_and_target_loss_reset_gesture_state(self):
        gate = GestureGate(stable_frames=3)
        for timestamp in (0, 33):
            self.assertIsNone(gate.observe("target:Right", "Open_Palm", 0.9, "play_pause", timestamp))
        gate.reset_except(set())
        self.assertIsNone(gate.observe("target:Right", "Open_Palm", 0.9, "play_pause", 66))
        self.assertIsNone(gate.observe("target:Right", "Open_Palm", 0.65, "play_pause", 99))
        self.assertIsNone(gate.observe("target:Right", "Open_Palm", 0.9, "play_pause", 132))
        self.assertIsNone(gate.observe("target:Right", "Open_Palm", 0.9, "play_pause", 165))
        self.assertTrue(gate.observe("target:Right", "Open_Palm", 0.9, "play_pause", 198))

    def test_action_cooldown_applies_across_hands(self):
        gate = GestureGate(stable_frames=1, cooldown_ms=800)
        self.assertTrue(gate.observe("person:Left", "Open_Palm", 0.9, "play_pause", 1000))
        self.assertFalse(gate.observe("person:Right", "Open_Palm", 0.9, "play_pause", 1500))
        self.assertTrue(gate.observe("person:Right", "Thumb_Up", 0.9, "volume_up", 1500))

    def test_controller_state_reset_preserves_action_cooldown_when_requested(self):
        gate = GestureGate(stable_frames=1, cooldown_ms=800)
        self.assertTrue(gate.observe("person-1:Right", "Thumb_Up", 0.9, "volume_up", 1000))
        gate.reset(preserve_cooldowns=True)
        self.assertFalse(gate.observe("person-1:Right", "Thumb_Up", 0.9, "volume_up", 1500))
        self.assertIsNone(gate.observe("person-1:Right", None, 0.0, "none", 1600))
        self.assertTrue(gate.observe("person-1:Right", "Thumb_Up", 0.9, "volume_up", 1800))

    def test_mapping_validation(self):
        self.assertEqual(validate_mappings(DEFAULT_MAPPINGS), DEFAULT_MAPPINGS)
        invalid = dict(DEFAULT_MAPPINGS)
        invalid["Victory"] = "run_shell"
        with self.assertRaises(ValueError):
            validate_mappings(invalid)
        with self.assertRaises(ValueError):
            validate_mappings({"Open_Palm": "none"})
        self.assertIn("none", ACTIONS)
        self.assertIn("play_pause", ACTIONS)
        self.assertIn("mute_toggle", ACTIONS)

    def test_rtsp_validation(self):
        address = "rtsp://user:pass@camera.local:554/stream"
        self.assertEqual(validate_rtsp_url(address), address)
        for invalid in ("http://camera.local/live", "rtsp://", "not a url"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_rtsp_url(invalid)

    def test_gesture_event_contract_contains_21_normalized_landmarks(self):
        landmarks = [{"x": 0.5, "y": 0.25, "z": -0.1} for _ in range(21)]
        event = build_gesture_event(
            target_id="id-1",
            target_name="Alice",
            gesture="Victory",
            confidence=0.93,
            handedness="Right",
            timestamp_ms=1234,
            action="none",
            action_triggered=False,
            landmarks=landmarks,
        )
        self.assertEqual(
            set(event),
            {
                "type", "target_id", "target_name", "gesture", "confidence", "handedness",
                "timestamp_ms", "action", "action_triggered", "landmarks",
            },
        )
        self.assertEqual(event["type"], "gesture")
        self.assertEqual(len(event["landmarks"]), 21)
        with self.assertRaises(ValueError):
            build_gesture_event(
                target_id="id-1", target_name="Alice", gesture="Victory", confidence=0.93,
                handedness="Right", timestamp_ms=1234, action="none", action_triggered=False,
                landmarks=landmarks[:20],
            )

    def test_controller_event_reports_state_and_temporary_track(self):
        event = build_controller_event(
            state="locked", track_id="person-2", timestamp_ms=1234, reason="ok_gesture"
        )
        self.assertEqual(event["type"], "controller")
        self.assertEqual(event["state"], "locked")
        self.assertEqual(event["track_id"], "person-2")
        with self.assertRaises(ValueError):
            build_controller_event(state="locked", track_id=None, timestamp_ms=1234, reason="bad")


if __name__ == "__main__":
    unittest.main()
