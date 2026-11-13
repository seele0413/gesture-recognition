import unittest
from types import SimpleNamespace

from app.controller import ControllerLock, analyze_v_gesture, is_v_gesture


def make_v_hand():
    points = [SimpleNamespace(x=0.5, y=0.5, z=0.0) for _ in range(21)]
    points[0] = SimpleNamespace(x=0.52, y=0.82, z=0.0)
    points[5] = SimpleNamespace(x=0.40, y=0.70, z=0.0)
    points[6] = SimpleNamespace(x=0.40, y=0.60, z=0.0)
    points[8] = SimpleNamespace(x=0.35, y=0.43, z=0.0)
    points[9] = SimpleNamespace(x=0.48, y=0.70, z=0.0)
    points[10] = SimpleNamespace(x=0.48, y=0.60, z=0.0)
    points[12] = SimpleNamespace(x=0.55, y=0.43, z=0.0)
    points[13] = SimpleNamespace(x=0.56, y=0.70, z=0.0)
    points[14] = SimpleNamespace(x=0.56, y=0.62, z=0.0)
    points[16] = SimpleNamespace(x=0.60, y=0.66, z=0.0)
    points[17] = SimpleNamespace(x=0.65, y=0.70, z=0.0)
    points[18] = SimpleNamespace(x=0.65, y=0.62, z=0.0)
    points[20] = SimpleNamespace(x=0.69, y=0.66, z=0.0)
    return points


class VGestureTests(unittest.TestCase):
    def test_v_geometry_is_recognized(self):
        self.assertTrue(is_v_gesture(make_v_hand()))
        result = analyze_v_gesture(make_v_hand())
        self.assertTrue(result["is_v"])
        self.assertEqual(result["reason"], "V 字手势几何符合")

    def test_open_palm_is_not_mistaken_for_v_sign(self):
        points = make_v_hand()
        points[16] = SimpleNamespace(x=0.56, y=0.43, z=0.0)
        points[20] = SimpleNamespace(x=0.65, y=0.43, z=0.0)
        self.assertFalse(is_v_gesture(points))

    def test_one_extended_finger_is_not_enough(self):
        points = make_v_hand()
        points[12] = SimpleNamespace(x=0.52, y=0.66, z=0.0)
        self.assertFalse(is_v_gesture(points))

    def test_v_fingers_must_be_separated(self):
        points = make_v_hand()
        points[12] = SimpleNamespace(x=0.37, y=0.43, z=0.0)
        result = analyze_v_gesture(points)
        self.assertFalse(result["is_v"])
        self.assertIn("分开幅度不足", result["reason"])

    def test_smaller_distant_v_hand_is_recognized(self):
        points = make_v_hand()
        for point in points:
            point.x = 0.5 + (point.x - 0.5) * 0.60
            point.y = 0.5 + (point.y - 0.5) * 0.60
        self.assertTrue(analyze_v_gesture(points)["is_v"])

    def test_extremely_small_hand_is_still_rejected(self):
        points = make_v_hand()
        for point in points:
            point.x = 0.5 + (point.x - 0.5) * 0.02
            point.y = 0.5 + (point.y - 0.5) * 0.02
        result = analyze_v_gesture(points)
        self.assertFalse(result["is_v"])
        self.assertIn("过小", result["reason"])

    def test_missing_landmarks_are_rejected(self):
        self.assertFalse(is_v_gesture(make_v_hand()[:20]))
        self.assertIn("21", analyze_v_gesture(make_v_hand()[:20])["reason"])


class ControllerLockTests(unittest.TestCase):
    def test_three_v_detections_within_five_frames_lock_same_person(self):
        lock = ControllerLock()
        self.assertIsNone(lock.observe_lock_candidates(["person-1"], 100))
        self.assertEqual(lock.snapshot()["lock_progress"], 1)
        self.assertIsNone(lock.observe_lock_candidates([], 133))
        self.assertEqual(lock.snapshot()["lock_progress"], 1)
        self.assertIsNone(lock.observe_lock_candidates(["person-1"], 166))
        self.assertIsNone(lock.observe_lock_candidates([], 199))
        self.assertEqual(lock.observe_lock_candidates(["person-1"], 232), "locked")
        self.assertEqual(lock.snapshot()["track_id"], "person-1")

    def test_two_v_detections_within_five_frames_lock_same_person(self):
        lock = ControllerLock()
        self.assertIsNone(lock.observe_lock_candidates(["person-1"], 100))
        self.assertEqual(lock.snapshot()["lock_progress"], 1)
        self.assertIsNone(lock.observe_lock_candidates([], 133))
        self.assertEqual(lock.observe_lock_candidates(["person-1"], 166), "locked")
        self.assertEqual(lock.snapshot()["track_id"], "person-1")

    def test_multiple_or_unassociated_v_hands_do_not_lock(self):
        lock = ControllerLock()
        for _ in range(4):
            self.assertIsNone(lock.observe_lock_candidates(["person-1", "person-2"], 100))
        self.assertIsNone(lock.observe_lock_candidates([None], 100))
        self.assertEqual(lock.snapshot()["state"], "unlocked")

    def test_switching_candidate_person_resets_lock_progress(self):
        lock = ControllerLock()
        self.assertIsNone(lock.observe_lock_candidates(["person-1"], 100))
        self.assertIsNone(lock.observe_lock_candidates(["person-1"], 133))
        self.assertEqual(lock.snapshot()["lock_progress"], 2)
        self.assertIsNone(lock.observe_lock_candidates(["person-2"], 166))
        self.assertEqual(lock.snapshot()["lock_progress"], 1)
        self.assertIsNone(lock.observe_lock_candidates(["person-1"], 199))
        self.assertEqual(lock.snapshot()["lock_progress"], 1)

    def test_candidate_window_expires_after_misses(self):
        lock = ControllerLock()
        self.assertIsNone(lock.observe_lock_candidates(["person-1"], 100))
        for timestamp in (133, 166, 199, 232, 265):
            self.assertIsNone(lock.observe_lock_candidates([], timestamp))
        self.assertEqual(lock.snapshot()["lock_progress"], 0)

    def test_track_dropout_enters_suspect_then_reacquiring_before_timeout(self):
        lock = ControllerLock(stable_frames=1, window_frames=1)
        lock.observe_lock_candidates(["person-1"], 100)
        self.assertEqual(lock.update_tracking(set(), 200), [("suspect", "track_unmatched")])
        self.assertEqual(lock.snapshot()["state"], "suspect")
        self.assertEqual(lock.update_tracking(set(), 849), [])
        self.assertEqual(lock.update_tracking(set(), 850), [("reacquiring", "track_reacquiring")])
        self.assertEqual(lock.snapshot()["state"], "reacquiring")
        self.assertEqual(lock.update_tracking(set(), 3699), [])
        self.assertEqual(lock.update_tracking(set(), 3700), [("unlocked", "track_timeout")])
        self.assertIsNone(lock.snapshot()["track_id"])
        self.assertIsNone(lock.snapshot()["controller_id"])

    def test_track_reappearing_during_suspect_recovers_same_controller_session(self):
        lock = ControllerLock(stable_frames=1, window_frames=1)
        lock.observe_lock_candidates(["person-1"], 100)
        controller_id = lock.snapshot()["controller_id"]
        self.assertEqual(lock.update_tracking(set(), 200), [("suspect", "track_unmatched")])
        self.assertEqual(lock.update_tracking({"person-1"}, 500), [("locked", "reacquired")])
        self.assertEqual(lock.snapshot()["controller_id"], controller_id)
        self.assertEqual(lock.snapshot()["track_id"], "person-1")

    def test_track_reappearing_during_reacquiring_recovers_same_controller_session(self):
        lock = ControllerLock(stable_frames=1, window_frames=1)
        lock.observe_lock_candidates(["person-1"], 100)
        self.assertEqual(lock.update_tracking(set(), 200), [("suspect", "track_unmatched")])
        self.assertEqual(lock.update_tracking(set(), 850), [("reacquiring", "track_reacquiring")])
        self.assertEqual(lock.update_tracking({"person-1"}, 1200), [("locked", "reacquired")])

    def test_track_returning_after_recovery_timeout_does_not_reactivate_old_controller(self):
        lock = ControllerLock(stable_frames=1, window_frames=1)
        lock.observe_lock_candidates(["person-1"], 100)
        controller_id = lock.snapshot()["controller_id"]
        lock.update_tracking(set(), 200)
        self.assertEqual(lock.update_tracking({"person-1"}, 3700), [("unlocked", "track_timeout")])
        self.assertIsNone(lock.snapshot()["controller_id"])
        self.assertNotEqual(lock.snapshot()["controller_id"], controller_id)

    def test_other_person_cannot_take_over_during_controller_recovery(self):
        lock = ControllerLock(stable_frames=1, window_frames=1)
        lock.observe_lock_candidates(["person-1"], 100)
        controller_id = lock.snapshot()["controller_id"]
        self.assertEqual(lock.update_tracking(set(), 200), [("suspect", "track_unmatched")])
        self.assertIsNone(lock.observe_lock_candidates(["person-2"], 300))
        self.assertEqual(lock.snapshot()["track_id"], "person-1")
        self.assertEqual(lock.snapshot()["controller_id"], controller_id)
        self.assertEqual(lock.snapshot()["state"], "suspect")

    def test_manual_unlock_clears_controller_identity_and_target(self):
        lock = ControllerLock(stable_frames=1, window_frames=1)
        lock.observe_lock_candidates(["person-1"], 100)
        self.assertIsNotNone(lock.snapshot()["controller_id"])
        self.assertTrue(lock.unlock())
        self.assertFalse(lock.unlock())
        self.assertEqual(lock.snapshot()["state"], "unlocked")
        self.assertIsNone(lock.snapshot()["controller_id"])


if __name__ == "__main__":
    unittest.main()
