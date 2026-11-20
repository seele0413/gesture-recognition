import unittest
from types import SimpleNamespace

from app.hand_tracking import HandTrackManager


def make_hand(*, x=0.5, y=0.5, handedness="Right", track_id=None, is_lock_gesture=False, scale=1.0):
    points = [SimpleNamespace(x=x, y=y, z=0.0) for _ in range(21)]
    points[0] = SimpleNamespace(x=x, y=y, z=0.0)
    points[5] = SimpleNamespace(x=x - 0.05 * scale, y=y, z=0.0)
    points[17] = SimpleNamespace(x=x + 0.05 * scale, y=y, z=0.0)
    return {"track_id": track_id, "handedness": handedness, "is_lock_gesture": is_lock_gesture, "landmarks": points}


class HandTrackManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = HandTrackManager()
        self.manager.observe_locked([make_hand(track_id="person-a")], "person-a", "controller-a", 100)

    def test_unique_recent_hand_motion_confirms_original_controller(self):
        hand = make_hand(x=0.53)
        self.assertEqual(self.manager.associate([hand], "person-a", "controller-a", 180), [hand])
        self.assertEqual(hand["track_id"], "person-a")
        self.assertTrue(hand["identity_confirmed"])
        self.assertAlmostEqual(hand["identity_match_distance"], 0.03, places=4)

    def test_different_handedness_is_not_matched(self):
        self.assertEqual(self.manager.associate([make_hand(handedness="Left")], "person-a", "controller-a", 150), [])

    def test_far_away_hand_is_not_matched(self):
        self.assertEqual(self.manager.associate([make_hand(x=0.9)], "person-a", "controller-a", 150), [])

    def test_ambiguous_same_side_hands_are_rejected(self):
        self.assertEqual(self.manager.associate([make_hand(x=0.50), make_hand(x=0.51)], "person-a", "controller-a", 150), [])

    def test_hand_associated_to_another_person_is_not_stolen(self):
        self.assertEqual(self.manager.associate([make_hand(track_id="person-b")], "person-a", "controller-a", 150), [])

    def test_lock_gesture_is_not_reused_as_control_hand(self):
        self.assertEqual(self.manager.associate([make_hand(is_lock_gesture=True)], "person-a", "controller-a", 150), [])

    def test_track_expires_after_suspect_window(self):
        self.assertEqual(self.manager.associate([make_hand()], "person-a", "controller-a", 751), [])
        self.assertEqual(self.manager.snapshot()["hand_track_count"], 0)

    def test_new_controller_session_cannot_reuse_old_hand_track(self):
        self.assertEqual(self.manager.associate([make_hand()], "person-a", "controller-b", 150), [])

    def test_multiple_same_side_locked_hands_do_not_overwrite_anchor(self):
        original = self.manager.snapshot()["hand_track_count"]
        self.manager.observe_locked([make_hand(x=0.4, track_id="person-a"), make_hand(x=0.6, track_id="person-a")], "person-a", "controller-a", 150)
        self.assertEqual(self.manager.snapshot()["hand_track_count"], original)


if __name__ == "__main__":
    unittest.main()
