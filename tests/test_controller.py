import unittest
from types import SimpleNamespace

from app.controller import ControllerLock, analyze_ok_gesture, is_ok_gesture


def make_ok_hand():
    points = [SimpleNamespace(x=0.5, y=0.8, z=0.0) for _ in range(21)]
    points[0] = SimpleNamespace(x=0.5, y=0.82, z=0.0)
    points[2] = SimpleNamespace(x=0.43, y=0.68, z=0.0)
    points[3] = SimpleNamespace(x=0.40, y=0.63, z=0.0)
    points[4] = SimpleNamespace(x=0.39, y=0.58, z=0.0)
    points[5] = SimpleNamespace(x=0.39, y=0.70, z=0.0)
    points[6] = SimpleNamespace(x=0.39, y=0.62, z=0.0)
    points[7] = SimpleNamespace(x=0.39, y=0.59, z=0.0)
    points[8] = SimpleNamespace(x=0.40, y=0.58, z=0.0)
    for mcp, pip, dip, tip, x in (
        (9, 10, 11, 12, 0.49),
        (13, 14, 15, 16, 0.57),
        (17, 18, 19, 20, 0.65),
    ):
        points[mcp] = SimpleNamespace(x=x, y=0.70, z=0.0)
        points[pip] = SimpleNamespace(x=x, y=0.61, z=0.0)
        points[dip] = SimpleNamespace(x=x, y=0.51, z=0.0)
        points[tip] = SimpleNamespace(x=x, y=0.41, z=0.0)
    return points


class OkGestureTests(unittest.TestCase):
    def test_ok_geometry_is_recognized(self):
        self.assertTrue(is_ok_gesture(make_ok_hand()))
        self.assertEqual(analyze_ok_gesture(make_ok_hand())["reason"], "OK 手势几何符合")

    def test_touching_thumb_and_index_without_extended_other_fingers_is_rejected(self):
        points = make_ok_hand()
        points[12] = SimpleNamespace(x=0.49, y=0.70, z=0.0)
        self.assertFalse(is_ok_gesture(points))

    def test_thumb_up_and_missing_landmarks_are_rejected(self):
        self.assertFalse(is_ok_gesture(make_ok_hand()[:20]))
        self.assertIn("21", analyze_ok_gesture(make_ok_hand()[:20])["reason"])
        points = make_ok_hand()
        points[4] = SimpleNamespace(x=0.20, y=0.40, z=0.0)
        self.assertFalse(is_ok_gesture(points))
        self.assertIn("距离偏大", analyze_ok_gesture(points)["reason"])


class ControllerLockTests(unittest.TestCase):
    def test_requires_five_consecutive_ok_frames_for_one_track(self):
        lock = ControllerLock(stable_frames=5)
        for _ in range(4):
            self.assertIsNone(lock.observe_lock_candidates(["person-1"], 100))
        self.assertEqual(lock.snapshot()["lock_progress"], 4)
        self.assertEqual(lock.observe_lock_candidates(["person-1"], 100), "locked")
        self.assertEqual(lock.snapshot()["track_id"], "person-1")

    def test_ambiguous_or_multiple_ok_tracks_do_not_lock(self):
        lock = ControllerLock(stable_frames=2)
        for _ in range(4):
            self.assertIsNone(lock.observe_lock_candidates(["person-1", "person-2"], 100))
        self.assertIsNone(lock.observe_lock_candidates([None], 100))
        self.assertEqual(lock.snapshot()["state"], "unlocked")

    def test_lost_track_pauses_then_recovers_or_times_out(self):
        lock = ControllerLock(stable_frames=1, lost_timeout_ms=2000)
        lock.observe_lock_candidates(["person-1"], 100)
        self.assertEqual(lock.update_tracking(set(), 200), [("lost", "track_unmatched")])
        self.assertEqual(lock.update_tracking({"person-1"}, 1500), [("locked", "reacquired")])
        self.assertEqual(lock.update_tracking(set(), 1600), [("lost", "track_unmatched")])
        self.assertEqual(lock.update_tracking(set(), 3600), [("unlocked", "track_timeout")])
        self.assertIsNone(lock.snapshot()["track_id"])

    def test_manual_unlock_clears_target(self):
        lock = ControllerLock(stable_frames=1)
        lock.observe_lock_candidates(["person-1"], 100)
        self.assertTrue(lock.unlock())
        self.assertFalse(lock.unlock())
        self.assertEqual(lock.snapshot()["state"], "unlocked")


if __name__ == "__main__":
    unittest.main()
