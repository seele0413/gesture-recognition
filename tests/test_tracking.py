import unittest
from types import SimpleNamespace

from app.tracking import PoseTrackManager
from app.vision import VisionProcessor


def landmark(x, y, visibility=1.0):
    return SimpleNamespace(x=x, y=y, z=0.0, visibility=visibility, presence=1.0)


def pose(center_x):
    points = [landmark(center_x, 0.5) for _ in range(33)]
    points[11] = landmark(center_x - 0.035, 0.35)
    points[12] = landmark(center_x + 0.035, 0.35)
    points[13] = landmark(center_x - 0.08, 0.40)
    points[14] = landmark(center_x + 0.08, 0.40)
    points[15] = landmark(center_x - 0.12, 0.48)
    points[16] = landmark(center_x + 0.12, 0.48)
    points[23] = landmark(center_x - 0.03, 0.57)
    points[24] = landmark(center_x + 0.03, 0.57)
    points[25] = landmark(center_x - 0.04, 0.75)
    points[26] = landmark(center_x + 0.04, 0.75)
    points[27] = landmark(center_x - 0.05, 0.92)
    points[28] = landmark(center_x + 0.05, 0.92)
    return points


class PoseTrackTests(unittest.TestCase):
    def test_track_ids_remain_stable_when_pose_order_changes(self):
        tracker = PoseTrackManager()
        first = tracker.update([pose(0.25), pose(0.75)], 640, 480, 100)
        ids_by_x = {round(item["center"][0], 2): item["track_id"] for item in first}
        second = tracker.update([pose(0.76), pose(0.24)], 640, 480, 133)
        reversed_ids = {round(item["center"][0], 2): item["track_id"] for item in second}
        self.assertEqual(reversed_ids[0.24], ids_by_x[0.25])
        self.assertEqual(reversed_ids[0.76], ids_by_x[0.75])

    def test_motion_prediction_reduces_cost_after_a_short_observation_gap(self):
        tracker = PoseTrackManager()
        tracker.update([pose(0.30)], 640, 480, 100)
        tracker.update([pose(0.35)], 640, 480, 200)
        track = tracker._tracks["person-1"]
        observation = tracker._features(0, pose(0.42))

        unpredicted_cost = tracker._cost(track, observation)
        predicted_cost = tracker._cost(track, observation, 400)
        resumed = tracker.update([pose(0.42)], 640, 480, 400)

        self.assertLess(predicted_cost, unpredicted_cost)
        self.assertEqual(resumed[0]["track_id"], "person-1")

    def test_track_output_contains_pixel_box_and_ambiguity_state(self):
        tracker = PoseTrackManager()
        result = tracker.update([pose(0.5)], 640, 480, 100)
        self.assertEqual(result[0]["track_id"], "person-1")
        self.assertEqual(len(result[0]["box"]), 4)
        self.assertEqual(len(result[0]["box_norm"]), 4)
        self.assertFalse(result[0]["ambiguous"])

    def test_upper_body_remains_trackable_when_hips_are_out_of_frame(self):
        tracker = PoseTrackManager()
        first_pose = pose(0.5)
        first_pose[23] = landmark(0.47, 0.58, visibility=0.1)
        first_pose[24] = landmark(0.53, 0.58, visibility=0.1)
        first = tracker.update([first_pose], 640, 480, 100)
        second_pose = pose(0.51)
        second_pose[23] = landmark(0.48, 0.58, visibility=0.1)
        second_pose[24] = landmark(0.54, 0.58, visibility=0.1)
        second = tracker.update([second_pose], 640, 480, 133)
        self.assertEqual(first[0]["track_id"], "person-1")
        self.assertEqual(second[0]["track_id"], "person-1")

    def test_hand_ambiguity_is_not_assigned_to_either_person(self):
        tracker = PoseTrackManager()
        tracks = tracker.update([pose(0.45), pose(0.55)], 640, 480, 100)
        wrist = landmark(0.5, 0.48)
        hand = [wrist] + [landmark(0.5, 0.5) for _ in range(20)]
        self.assertIsNone(VisionProcessor._associate_hand_to_track(hand, tracks))

    def test_hand_association_compares_best_wrist_per_person(self):
        def track(track_id, left_wrist, right_wrist):
            landmarks = [landmark(0.0, 0.0) for _ in range(33)]
            landmarks[15] = landmark(*left_wrist)
            landmarks[16] = landmark(*right_wrist)
            return {"track_id": track_id, "landmarks": landmarks, "ambiguous": False}

        tracks = [
            track("person-1", (0.40, 0.40), (0.41, 0.40)),
            track("person-2", (0.42, 0.40), (0.8, 0.8)),
        ]
        hand = [landmark(0.40, 0.40)] + [landmark(0.40, 0.40) for _ in range(20)]
        self.assertIsNone(VisionProcessor._associate_hand_to_track(hand, tracks))

    def test_hand_wrist_gate_scales_with_person_box_size(self):
        def track(track_id, wrist, box):
            landmarks = [landmark(0.0, 0.0) for _ in range(33)]
            landmarks[15] = landmark(*wrist)
            return {"track_id": track_id, "landmarks": landmarks, "box_norm": box, "ambiguous": False}

        hand = [landmark(0.5, 0.5)] + [landmark(0.5, 0.5) for _ in range(20)]
        small_person = track("small", (0.4, 0.5), [0.25, 0.35, 0.2, 0.2])
        large_person = track("large", (0.4, 0.5), [0.3, 0.3, 0.45, 0.45])

        self.assertIsNone(VisionProcessor._associate_hand_to_track(hand, [small_person]))
        self.assertEqual(VisionProcessor._associate_hand_to_track(hand, [large_person]), "large")

    def test_ambiguous_wrist_match_does_not_fall_back_to_a_single_person_box(self):
        def track(track_id, wrist_x, box):
            landmarks = [landmark(0.0, 0.0, visibility=0.1) for _ in range(33)]
            landmarks[15] = landmark(wrist_x, 0.5)
            return {
                "track_id": track_id,
                "landmarks": landmarks,
                "box_norm": box,
                "ambiguous": False,
            }

        tracks = [
            track("person-1", 0.49, [0.4, 0.4, 0.2, 0.2]),
            track("person-2", 0.51, [0.6, 0.4, 0.2, 0.2]),
        ]
        hand = [landmark(0.5, 0.5)] + [landmark(0.5, 0.5) for _ in range(20)]
        track_id, reason = VisionProcessor._associate_hand(hand, tracks)
        self.assertIsNone(track_id)
        self.assertIn("手腕关联有歧义", reason)

    def test_hand_falls_back_to_a_unique_person_box_when_wrists_are_invisible(self):
        invisible_wrist = [landmark(0.0, 0.0, visibility=0.1) for _ in range(33)]
        track = {
            "track_id": "person-1",
            "landmarks": invisible_wrist,
            "box_norm": [0.35, 0.35, 0.3, 0.3],
            "ambiguous": False,
        }
        hand = [landmark(0.5, 0.5) for _ in range(21)]
        self.assertEqual(VisionProcessor._associate_hand_to_track(hand, [track]), "person-1")

    def test_hand_inside_overlapping_person_boxes_remains_unassigned(self):
        invisible_wrist = [landmark(0.0, 0.0, visibility=0.1) for _ in range(33)]
        tracks = [
            {"track_id": "person-1", "landmarks": invisible_wrist, "box_norm": [0.3, 0.3, 0.4, 0.4], "ambiguous": False},
            {"track_id": "person-2", "landmarks": invisible_wrist, "box_norm": [0.4, 0.4, 0.4, 0.4], "ambiguous": False},
        ]
        hand = [landmark(0.5, 0.5) for _ in range(21)]
        self.assertIsNone(VisionProcessor._associate_hand_to_track(hand, tracks))


if __name__ == "__main__":
    unittest.main()
