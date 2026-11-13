import unittest
from types import SimpleNamespace

from app.controller_identity import ControllerIdentityManager


def make_track(track_id, center_x=0.5, center_y=0.45, first_seen_ms=100, ambiguous=False, confidence=0.95):
    points = [SimpleNamespace(x=center_x, y=center_y, visibility=1.0, presence=1.0) for _ in range(33)]
    offsets = {
        11: (-0.05, 0.00), 12: (0.05, 0.00),
        13: (-0.08, 0.08), 14: (0.08, 0.08),
        15: (-0.10, 0.18), 16: (0.10, 0.18),
        23: (-0.04, 0.25), 24: (0.04, 0.25),
    }
    for index, (dx, dy) in offsets.items():
        points[index] = SimpleNamespace(
            x=center_x + dx, y=center_y + dy, visibility=1.0, presence=1.0
        )
    return {
        "track_id": track_id,
        "center": (center_x, center_y),
        "box_norm": [center_x - 0.12, center_y - 0.02, 0.24, 0.42],
        "landmarks": points,
        "association_confidence": confidence,
        "ambiguous": ambiguous,
        "first_seen_ms": first_seen_ms,
    }


class ControllerIdentityManagerTests(unittest.TestCase):
    def test_controller_id_is_stable_when_same_track_returns(self):
        manager = ControllerIdentityManager()
        manager.bind("person-1", [make_track("person-1")], 100)
        controller_id = manager.snapshot()["controller_id"]
        self.assertEqual(manager.update_tracks([], 200), [("suspect", "track_unmatched")])
        self.assertEqual(manager.snapshot()["state"], "suspect")
        self.assertEqual(manager.update_tracks([make_track("person-1", first_seen_ms=100)], 500),
                         [("locked", "reacquired_same_track")])
        self.assertEqual(manager.snapshot()["controller_id"], controller_id)
        self.assertEqual(manager.snapshot()["track_id"], "person-1")

    def test_state_moves_to_reacquiring_after_suspect_grace(self):
        manager = ControllerIdentityManager(suspect_grace_ms=800, reacquire_timeout_ms=4000)
        manager.bind("person-1", [make_track("person-1")], 100)
        self.assertEqual(manager.update_tracks([], 200), [("suspect", "track_unmatched")])
        self.assertEqual(manager.update_tracks([], 999), [])
        self.assertEqual(manager.update_tracks([], 1000), [("reacquiring", "track_reacquiring")])
        self.assertEqual(manager.snapshot()["state"], "reacquiring")

    def test_new_track_can_rebind_when_pose_geometry_is_a_unique_match(self):
        manager = ControllerIdentityManager(suspect_grace_ms=800, reacquire_timeout_ms=4000)
        manager.bind("person-1", [make_track("person-1")], 100)
        controller_id = manager.snapshot()["controller_id"]
        self.assertEqual(manager.update_tracks([], 200), [("suspect", "track_unmatched")])
        candidate = make_track("person-3", first_seen_ms=300)
        self.assertEqual(manager.update_tracks([candidate], 1000), [("locked", "track_id_rebound")])
        snapshot = manager.snapshot()
        self.assertEqual(snapshot["controller_id"], controller_id)
        self.assertEqual(snapshot["track_id"], "person-3")
        self.assertEqual(snapshot["last_reacquisition_method"], "pose_geometry")
        self.assertEqual(snapshot["reacquisition_count"], 1)

    def test_track_seen_before_loss_is_not_allowed_to_take_over(self):
        manager = ControllerIdentityManager(suspect_grace_ms=800, reacquire_timeout_ms=4000)
        manager.bind("person-1", [make_track("person-1"), make_track("person-2", center_x=0.8)], 100)
        self.assertEqual(manager.update_tracks([make_track("person-2", center_x=0.8)], 200),
                         [("suspect", "track_unmatched")])
        self.assertEqual(manager.update_tracks([make_track("person-2", center_x=0.8)], 1100),
                         [("reacquiring", "track_reacquiring")])
        self.assertEqual(manager.snapshot()["track_id"], "person-1")
        self.assertEqual(manager.snapshot()["state"], "reacquiring")

    def test_ambiguous_or_low_confidence_track_cannot_reacquire(self):
        manager = ControllerIdentityManager(suspect_grace_ms=800, reacquire_timeout_ms=4000)
        manager.bind("person-1", [make_track("person-1")], 100)
        manager.update_tracks([], 200)
        ambiguous = make_track("person-2", first_seen_ms=300, ambiguous=True)
        low_confidence = make_track("person-3", first_seen_ms=300, confidence=0.2)
        self.assertEqual(manager.update_tracks([ambiguous, low_confidence], 1000),
                         [("reacquiring", "track_reacquiring")])
        self.assertEqual(manager.snapshot()["track_id"], "person-1")

    def test_multiple_equally_plausible_tracks_are_not_guessed(self):
        manager = ControllerIdentityManager(suspect_grace_ms=800, reacquire_timeout_ms=4000)
        manager.bind("person-1", [make_track("person-1")], 100)
        manager.update_tracks([], 200)
        candidates = [
            make_track("person-2", first_seen_ms=300),
            make_track("person-3", first_seen_ms=300),
        ]
        self.assertEqual(manager.update_tracks(candidates, 1000),
                         [("reacquiring", "track_reacquiring")])
        self.assertEqual(manager.snapshot()["track_id"], "person-1")

    def test_reacquisition_timeout_releases_controller_identity(self):
        manager = ControllerIdentityManager(suspect_grace_ms=800, reacquire_timeout_ms=4000)
        manager.bind("person-1", [make_track("person-1")], 100)
        self.assertEqual(manager.update_tracks([], 200), [("suspect", "track_unmatched")])
        self.assertEqual(manager.update_tracks([], 4199), [("reacquiring", "track_reacquiring")])
        self.assertEqual(manager.update_tracks([], 4200), [("unlocked", "track_timeout")])
        snapshot = manager.snapshot()
        self.assertEqual(snapshot["state"], "unlocked")
        self.assertIsNone(snapshot["controller_id"])
        self.assertIsNone(snapshot["track_id"])


if __name__ == "__main__":
    unittest.main()
