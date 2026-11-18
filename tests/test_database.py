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

    def test_display_pages_are_seeded_and_persisted(self):
        pages = self.store.get_display_pages()
        self.assertEqual([page["page_id"] for page in pages],
                         ["promo", "factory", "product", "company_website"])
        self.assertEqual(self.store.get_default_display_page_id(), "promo")
        reopened = ControlStore(legacy_path)
        self.assertEqual(reopened.get_display_page("company_website")["url"],
                         "https://www.zhcomking.com/")

    def test_legacy_database_migrates_four_display_pages_without_losing_settings(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        legacy_mappings = dict(DEFAULT_MAPPINGS)
        legacy_mappings["ILoveYou"] = "play_pause"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ("gesture_mappings", json.dumps(legacy_mappings)),
            )
            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ("gesture_confidence_threshold", json.dumps(0.65)),
            )

        migrated = ControlStore(legacy_path)
        pages = migrated.get_display_pages()
        self.assertEqual(
            [page["page_id"] for page in pages],
            ["promo", "factory", "product", "company_website"],
        )
        self.assertEqual(migrated.get_mappings(), legacy_mappings)
        self.assertEqual(migrated.get_gesture_confidence_threshold(), 0.65)

        reopened = ControlStore(self.path)
        self.assertEqual(
            [page["page_id"] for page in reopened.get_display_pages()],
            ["promo", "factory", "product", "company_website"],
        )

    def test_external_display_pages_can_be_created_updated_and_deleted(self):
        page = self.store.create_display_page({
            "page_id": "product_center", "title": "产品中心子页面",
            "description": "产品分类入口", "url": "https://www.zhcomking.com/products/",
            "page_type": "external", "parent_id": "company_website", "enabled": True,
        })
        self.assertEqual(page["parent_id"], "company_website")
        updated = self.store.update_display_page("product_center", {
            "title": "产品中心", "description": "官网产品目录",
            "url": "https://www.zhcomking.com/products/index.html",
            "parent_id": "company_website", "enabled": True,
        })
        self.assertEqual(updated["title"], "产品中心")
        self.assertTrue(self.store.delete_display_page("product_center"))
        self.assertIsNone(self.store.get_display_page("product_center"))

    def test_display_page_default_cannot_be_deleted(self):
        self.store.set_default_display_page_id("company_website")
        with self.assertRaisesRegex(ValueError, "默认展示页面"):
            self.store.delete_display_page("company_website")
        with self.assertRaisesRegex(ValueError, "默认展示页面"):
            self.store.delete_display_page("company_website")

    def test_display_page_with_children_cannot_be_deleted(self):
        self.store.create_display_page({
            "page_id": "product_center", "title": "产品中心",
            "url": "https://www.zhcomking.com/products/", "page_type": "external",
            "parent_id": "company_website", "enabled": True,
        })
        with self.assertRaisesRegex(ValueError, "子页面"):
            self.store.delete_display_page("company_website")

    def test_display_page_referenced_by_workflow_cannot_be_deleted(self):
        workflow = new_workflow("引用网页的工作流")
        workflow["nodes"][0].update({
            "action": "web.navigate_page", "params": {"page_id": "company_website"},
        })
        self.store.save_workflow(workflow)
        with self.assertRaisesRegex(ValueError, "工作流引用"):
            self.store.delete_display_page("company_website")

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

    def test_pointer_settings_are_validated_and_persisted(self):
        defaults = self.store.get_pointer_settings()
        self.assertEqual(defaults["min_cutoff"], 1.0)
        updated = self.store.set_pointer_settings({"min_cutoff": 1.8, "press_stable_frames": 3})
        self.assertEqual(updated["min_cutoff"], 1.8)
        self.assertEqual(updated["press_stable_frames"], 3)
        reopened = ControlStore(self.path)
        self.assertEqual(reopened.get_pointer_settings()["min_cutoff"], 1.8)
        self.assertEqual(reopened.get_pointer_settings()["press_stable_frames"], 3)
        with self.assertRaises(ValueError):
            self.store.set_pointer_settings({"press_threshold": 0.7, "release_threshold": 0.6})

    def test_corrupt_pointer_settings_are_reset_to_safe_defaults(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE settings SET value = ? WHERE key = ?",
                (json.dumps({"min_cutoff": float("nan")}), "pointer_settings"),
            )
        reopened = ControlStore(self.path)
        self.assertEqual(reopened.get_pointer_settings(), self.store.get_pointer_settings())

    def test_controller_recovery_states_are_persistable(self):
        self.store.begin_session("session-recovery", 100)
        self.store.update_controller("session-recovery", "suspect", "person-1", 200)
        self.store.update_controller("session-recovery", "reacquiring", "person-1", 900)
        with sqlite3.connect(self.store.path) as connection:
            row = connection.execute(
                "SELECT state, track_id FROM controller_sessions WHERE session_id = ?",
                ("session-recovery",),
            ).fetchone()
        self.assertEqual(row, ("reacquiring", "person-1"))

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
