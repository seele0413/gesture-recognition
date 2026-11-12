import unittest
from types import SimpleNamespace

from app.pointer import HandPointerController


def make_hand(*, track_id="person-1", handedness="Right", confidence=0.9, is_ok=False):
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
        "is_ok": is_ok,
        "landmarks": points,
    }


class HandPointerControllerTests(unittest.TestCase):
    def setUp(self):
        self.pointer = HandPointerController(max_update_hz=1000000)
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

    def test_pinch_uses_hysteresis_and_releases(self):
        hover = self.pointer.update([make_hand()], "locked", "person-1", 100)
        self.assertFalse(hover["pressed"])
        pressed = self.pointer.update([self.pinch(make_hand(), 0.52)], "locked", "person-1", 120)
        self.assertTrue(pressed["pressed"])
        held = self.pointer.update([self.pinch(make_hand(), 0.56)], "locked", "person-1", 140)
        self.assertTrue(held["pressed"])
        up = self.pointer.update([self.pinch(make_hand(), 0.62)], "locked", "person-1", 160)
        self.assertFalse(up["pressed"])

    def test_missing_hand_emits_release(self):
        self.pointer.update([make_hand()], "locked", "person-1", 100)
        self.pointer.update([self.pinch(make_hand(), 0.52)], "locked", "person-1", 120)
        release = self.pointer.update([], "locked", "person-1", 140)
        self.assertFalse(release["active"])
        self.assertFalse(release["pressed"])

    def test_ok_hand_is_not_used_as_drag_pointer(self):
        self.assertIsNone(self.pointer.update([make_hand(is_ok=True)], "locked", "person-1", 100))

    def test_disabling_pointer_releases_active_state(self):
        self.pointer.update([make_hand()], "locked", "person-1", 100)
        release = self.pointer.set_enabled(False, 110)
        self.assertFalse(release["active"])
        self.assertFalse(release["pressed"])
        self.assertIsNone(self.pointer.update([make_hand()], "locked", "person-1", 120))


if __name__ == "__main__":
    unittest.main()
