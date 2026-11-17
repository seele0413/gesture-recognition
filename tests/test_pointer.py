import math
import unittest
from types import SimpleNamespace

from app.pointer import HandPointerController


def make_hand(*, track_id="person-1", handedness="Right", confidence=0.9, is_lock_gesture=False):
    points = [SimpleNamespace(x=0.5, y=0.5, z=0.0) for _ in range(21)]
    points[5] = SimpleNamespace(x=0.40, y=0.50, z=0.0)
    points[6] = SimpleNamespace(x=0.50, y=0.50, z=0.0)
    points[8] = SimpleNamespace(x=0.65, y=0.50, z=0.0)
    points[17] = SimpleNamespace(x=0.60, y=0.50, z=0.0)
    points[4] = SimpleNamespace(x=0.65, y=0.78, z=0.0)
    return {
        "track_id": track_id,
        "handedness": handedness,
        "confidence": confidence,
        "gesture": "Pointing_Up",
        "is_lock_gesture": is_lock_gesture,
        "landmarks": points,
    }


class HandPointerControllerTests(unittest.TestCase):
    def setUp(self):
        self.pointer = HandPointerController(max_update_hz=60)
        self.pointer.min_update_interval = 0.0
        self.pointer.set_enabled(True)

    @staticmethod
    def pinch(hand, y):
        hand["landmarks"][4] = SimpleNamespace(x=0.65, y=y, z=0.0)
        return hand

    def test_only_locked_controller_hand_can_drive_pointer(self):
        hand = make_hand()
        self.assertIsNone(self.pointer.update([hand], "unlocked", None, 100))
        self.assertIsNone(self.pointer.update([make_hand(track_id="person-2")], "locked", "person-1", 110))
        event = self.pointer.update([hand], "locked", "person-1", 120)
        self.assertIsNotNone(event)
        self.assertTrue(event["active"])
        self.assertFalse(event["pressed"])
        self.assertEqual(event["track_id"], "person-1")
        self.assertAlmostEqual(event["x"], 0.65, places=4)

    def test_pinch_requires_stable_press_and_release_frames(self):
        hover = self.pointer.update([make_hand()], "locked", "person-1", 100)
        self.assertFalse(hover["pressed"])
        first_press = self.pointer.update([self.pinch(make_hand(), 0.52)], "locked", "person-1", 120)
        self.assertFalse(first_press["pressed"])
        pressed = self.pointer.update([self.pinch(make_hand(), 0.52)], "locked", "person-1", 140)
        self.assertTrue(pressed["pressed"])
        held = self.pointer.update([self.pinch(make_hand(), 0.56)], "locked", "person-1", 160)
        self.assertTrue(held["pressed"])
        first_release = self.pointer.update([self.pinch(make_hand(), 0.62)], "locked", "person-1", 180)
        self.assertTrue(first_release["pressed"])
        released = self.pointer.update([self.pinch(make_hand(), 0.62)], "locked", "person-1", 200)
        self.assertFalse(released["pressed"])

    def test_suspect_pointer_requires_confirmed_hand_identity(self):
        self.assertIsNone(self.pointer.update(
            [make_hand()], "suspect", "person-1", 100,
            identity_confirmed=False, controller_id="controller-1",
        ))
        event = self.pointer.update(
            [make_hand()], "suspect", "person-1", 120,
            identity_confirmed=True, controller_id="controller-1",
        )
        self.assertIsNotNone(event)
        self.assertTrue(event["active"])
        self.assertTrue(event["identity_confirmed"])
        self.assertEqual(event["controller_id"], "controller-1")

    def test_unconfirmed_suspect_releases_an_active_drag(self):
        self.pointer.update([make_hand()], "locked", "person-1", 100)
        self.pointer.update([self.pinch(make_hand(), 0.52)], "locked", "person-1", 120)
        pressed = self.pointer.update([self.pinch(make_hand(), 0.52)], "locked", "person-1", 125)
        self.assertTrue(pressed["pressed"])
        released = self.pointer.update(
            [], "suspect", "person-1", 130, identity_confirmed=False, controller_id="controller-1",
        )
        self.assertIsNotNone(released)
        self.assertFalse(released["active"])
        self.assertFalse(released["pressed"])

    def test_short_detection_dropout_keeps_cursor_visible(self):
        first = self.pointer.update([make_hand()], "locked", "person-1", 100)
        self.assertTrue(first["active"])
        self.assertIsNone(self.pointer.update([], "locked", "person-1", 220))
        recovered = self.pointer.update([make_hand()], "locked", "person-1", 260)
        self.assertTrue(recovered["active"])
        self.assertAlmostEqual(recovered["x"], 0.65, places=4)

    def test_pressed_dropout_releases_drag_but_keeps_cursor_briefly(self):
        self.pointer.update([make_hand()], "locked", "person-1", 100)
        self.pointer.update([self.pinch(make_hand(), 0.52)], "locked", "person-1", 120)
        self.pointer.update([self.pinch(make_hand(), 0.52)], "locked", "person-1", 130)
        release = self.pointer.update([], "locked", "person-1", 140)
        self.assertTrue(release["active"])
        self.assertFalse(release["pressed"])
        self.assertIsNone(self.pointer.update([], "locked", "person-1", 300))
        hidden = self.pointer.update([], "locked", "person-1", 500)
        self.assertFalse(hidden["active"])
        self.assertFalse(hidden["pressed"])

    def test_cursor_hides_after_dropout_grace_expires(self):
        self.pointer.update([make_hand()], "locked", "person-1", 100)
        hidden = self.pointer.update([], "locked", "person-1", 451)
        self.assertFalse(hidden["active"])

    def test_more_sensitive_pinch_threshold(self):
        hand = make_hand()
        hand["landmarks"][4] = SimpleNamespace(x=0.72, y=0.50, z=0.0)
        first = self.pointer.update([hand], "locked", "person-1", 100)
        self.assertTrue(first["active"])
        self.assertFalse(first["pressed"])
        event = self.pointer.update([hand], "locked", "person-1", 120)
        self.assertTrue(event["pressed"])

    def test_relaxed_index_angle_keeps_pointer_active(self):
        hand = make_hand()
        angle = math.radians(35)
        hand["landmarks"][8] = SimpleNamespace(
            x=0.50 + 0.10 * math.cos(angle),
            y=0.50 + 0.10 * math.sin(angle),
            z=0.0,
        )
        event = self.pointer.update([hand], "locked", "person-1", 100)
        self.assertIsNotNone(event)
        self.assertTrue(event["active"])

    def test_one_euro_filter_smooths_small_jitter(self):
        from app.pointer import OneEuroFilter

        smoother = OneEuroFilter(min_cutoff=1.0, beta=0.0)
        self.assertAlmostEqual(smoother.filter(0.5, 100), 0.5)
        filtered = smoother.filter(0.6, 116)
        self.assertGreater(filtered, 0.5)
        self.assertLess(filtered, 0.6)

    def test_one_euro_filter_increases_responsiveness_for_fast_motion(self):
        from app.pointer import OneEuroFilter

        slow = OneEuroFilter(min_cutoff=1.0, beta=0.0)
        fast = OneEuroFilter(min_cutoff=1.0, beta=0.5)
        slow.filter(0.2, 100)
        fast.filter(0.2, 100)
        slow_value = slow.filter(0.8, 116)
        fast_value = fast.filter(0.8, 116)
        self.assertGreater(fast_value, slow_value)

    def test_pointer_settings_are_validated_and_applied(self):
        settings = self.pointer.set_settings({"min_cutoff": 1.5, "press_stable_frames": 3})
        self.assertEqual(settings["min_cutoff"], 1.5)
        self.assertEqual(settings["press_stable_frames"], 3)
        with self.assertRaises(ValueError):
            self.pointer.set_settings({"press_threshold": 0.6, "release_threshold": 0.5})
        with self.assertRaises(ValueError):
            self.pointer.set_settings({"unknown_option": 1})
        with self.assertRaises(ValueError):
            self.pointer.set_settings({"beta": float("nan")})

    def test_pointer_event_exposes_controller_and_hand_track_identity(self):
        hand = make_hand()
        hand["hand_track_id"] = "hand-7"
        event = self.pointer.update(
            [hand], "locked", "person-1", 100, controller_id="controller-7",
        )
        self.assertEqual(event["controller_id"], "controller-7")
        self.assertEqual(event["hand_track_id"], "hand-7")
        self.assertTrue(event["identity_confirmed"])

    def test_one_euro_filter_handles_repeated_and_reversed_timestamps(self):
        from app.pointer import OneEuroFilter

        smoother = OneEuroFilter()
        self.assertEqual(smoother.filter(0.2, 100), 0.2)
        values = [
            smoother.filter(0.3, 100),
            smoother.filter(0.4, 90),
            smoother.filter(0.5, 101),
        ]
        self.assertTrue(all(math.isfinite(value) for value in values))
        smoother.reset()
        self.assertEqual(smoother.filter(0.7, 10), 0.7)

    def test_controller_v_sign_is_not_used_as_drag_pointer(self):
        self.assertIsNone(self.pointer.update([make_hand(is_lock_gesture=True)], "locked", "person-1", 100))

    def test_disabling_pointer_releases_active_state(self):
        self.pointer.update([make_hand()], "locked", "person-1", 100)
        release = self.pointer.set_enabled(False, 110)
        self.assertFalse(release["active"])
        self.assertFalse(release["pressed"])
        self.assertIsNone(self.pointer.update([make_hand()], "locked", "person-1", 120))


if __name__ == "__main__":
    unittest.main()
