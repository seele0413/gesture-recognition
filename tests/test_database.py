import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.control import DEFAULT_MAPPINGS, LEGACY_DEFAULT_MAPPINGS
from app.database import ControlStore
from app.workflow import new_workflow


class ControlStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "data.sqlite3"
        self.store = ControlStore(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_mappings_are_persisted(self):
        self.assertEqual(self.store.get_mappings(), DEFAULT_MAPPINGS)
        changed = dict(DEFAULT_MAPPINGS)
        changed["ILoveYou"] = "play_pause"
        self.store.set_mappings(changed)
        self.assertEqual(self.store.get_mappings(), changed)

    def test_gesture_confidence_threshold_is_persisted_and_mappings_remain_unchanged(self):
        self.assertEqual(self.store.get_gesture_confidence_threshold(), 0.6)
        mappings = self.store.get_mappings()
        self.assertEqual(self.store.set_gesture_confidence_threshold(0.65), 0.65)
        reopened = ControlStore(self.path)
        self.assertEqual(reopened.get_gesture_confidence_threshold(), 0.65)
        self.assertEqual(reopened.get_mappings(), mappings)
        with self.assertRaises(ValueError):
            self.store.set_gesture_confidence_threshold(0.63)

    def test_invalid_stored_confidence_threshold_migrates_to_default(self):
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE settings SET value = ? WHERE key = ?", (json.dumps(0.63), "gesture_confidence_threshold")
            )
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(ControlStore(self.path).get_gesture_confidence_threshold(), 0.6)

    def test_temporary_session_and_gesture_metadata_are_cleared(self):
        self.store.begin_session("session-1", 100)
        self.store.update_controller("session-1", "locked", "person-1", 120)
        self.store.record_gesture(
            "session-1",
            {
                "target_id": "person-1",
                "gesture": "Thumb_Up",
                "confidence": 0.93,
                "handedness": "Right",
                "action": "volume_up",
                "action_triggered": True,
                "timestamp_ms": 200,
            },
        )
        self.assertEqual(self.store.get_recent_gestures("session-1")[0]["track_id"], "person-1")
        self.store.clear_temporary("session-1")
        self.assertEqual(self.store.get_recent_gestures("session-1"), [])

    def test_existing_face_table_is_preserved_but_not_used_and_mappings_survive(self):
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "CREATE TABLE identities (id TEXT PRIMARY KEY, name TEXT, embedding TEXT, created_at TEXT)"
            )
            connection.execute(
                "INSERT INTO identities VALUES ('old', 'Legacy', '[1, 0]', '2026-01-01')"
            )
            changed = dict(LEGACY_DEFAULT_MAPPINGS)
            changed["Victory"] = "reset_value"
            connection.execute(
                "UPDATE settings SET value = ? WHERE key = ?",
                (json.dumps(changed), "gesture_mappings"),
            )
            connection.commit()
        finally:
            connection.close()
        reopened = ControlStore(self.path)
        self.assertEqual(reopened.get_mappings()["Victory"], "none")
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM identities").fetchone()[0], 1)
        finally:
            connection.close()

    def test_gesture_event_history_is_bounded(self):
        self.store.begin_session("session-2", 100)
        event = {
            "target_id": "person-1",
            "gesture": "Thumb_Up",
            "confidence": 0.9,
            "handedness": "Right",
            "action": "volume_up",
            "action_triggered": True,
            "timestamp_ms": 200,
        }
        self.store.MAX_GESTURE_EVENTS = 3
        for index in range(5):
            self.store.record_gesture("session-2", {**event, "timestamp_ms": index})
        self.assertEqual(len(self.store.get_recent_gestures("session-2", 10)), 3)

    def test_workflow_definition_versions_and_runs_persist_without_changing_mappings(self):
        workflow = new_workflow("持久化工作流")
        saved = self.store.save_workflow(workflow)
        saved["description"] = "second version"
        saved = self.store.save_workflow(saved)
        self.assertEqual(saved["version"], 2)
        run = {
            "run_id": "run-1", "workflow_id": saved["id"], "workflow_version": saved["version"],
            "status": "success", "mode": "dry_run", "created_at": "2026-11-11T00:00:00+00:00",
            "result": [{"node_id": "play", "status": "simulated"}],
        }
        self.store.create_workflow_run(run)
        self.store.save_workflow_step("run-1", {
            "node_id": "play", "action": "video.play", "status": "simulated",
            "result": {"simulated": True}, "started_at": "2026-11-11T00:00:00+00:00",
        })
        reopened = ControlStore(self.path)
        self.assertEqual(reopened.get_workflow(saved["id"])["version"], 2)
        self.assertEqual([item["version"] for item in reopened.get_workflow_versions(saved["id"])], [2, 1])
        self.assertEqual(reopened.get_workflow_run("run-1")["status"], "success")
        self.assertEqual(reopened.get_workflow_run("run-1")["steps"][0]["status"], "simulated")
        self.assertEqual(reopened.get_mappings(), DEFAULT_MAPPINGS)

    def test_saving_unchanged_workflow_does_not_create_duplicate_version(self):
        saved = self.store.save_workflow(new_workflow("不重复版本"))

        unchanged = self.store.save_workflow(saved)

        self.assertEqual(unchanged["version"], 1)
        self.assertEqual([item["version"] for item in self.store.get_workflow_versions(saved["id"])], [1])

    def test_default_legacy_mappings_migrate_to_player_actions(self):
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE settings SET value = ? WHERE key = ?",
                (json.dumps(LEGACY_DEFAULT_MAPPINGS), "gesture_mappings"),
            )
            connection.commit()
        finally:
            connection.close()
        reopened = ControlStore(self.path)
        self.assertEqual(reopened.get_mappings(), DEFAULT_MAPPINGS)

    def test_previous_default_victory_mute_mapping_migrates_to_reserved_lock_gesture(self):
        previous = dict(DEFAULT_MAPPINGS)
        previous["Victory"] = "mute_toggle"
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE settings SET value = ? WHERE key = ?",
                (json.dumps(previous), "gesture_mappings"),
            )
            connection.commit()
        finally:
            connection.close()
        reopened = ControlStore(self.path)
        self.assertEqual(reopened.get_mappings()["Victory"], "none")

    def test_custom_legacy_actions_keep_their_meaning_when_migrated(self):
        connection = sqlite3.connect(self.path)
        custom = dict(LEGACY_DEFAULT_MAPPINGS)
        custom["Victory"] = "toggle_switch"
        custom["Closed_Fist"] = "none"
        try:
            connection.execute(
                "UPDATE settings SET value = ? WHERE key = ?",
                (json.dumps(custom), "gesture_mappings"),
            )
            connection.commit()
        finally:
            connection.close()
        reopened = ControlStore(self.path)
        expected = dict(DEFAULT_MAPPINGS)
        expected["Victory"] = "none"
        expected["Closed_Fist"] = "none"
        self.assertEqual(reopened.get_mappings(), expected)


if __name__ == "__main__":
    unittest.main()
