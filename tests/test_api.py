import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.workflow import new_workflow


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.promo_path = Path(self.temp_dir.name) / "promo.mp4"
        self.promo_path.write_bytes(b"test-video-content")
        self.client = TestClient(
            create_app(Path(self.temp_dir.name) / "data.sqlite3", self.promo_path)
        )

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def test_status_uses_tracks_and_controller_state(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("tracks", payload)
        self.assertFalse(payload["frame_ready"])
        self.assertFalse(payload["frame_fresh"])
        self.assertEqual(payload["frame_sequence"], 0)
        self.assertIn("reconnect_count", payload)
        self.assertIn("decoder", payload)
        self.assertEqual(payload["vision"]["hand_count"], 0)
        self.assertEqual(payload["controller"]["state"], "unlocked")
        self.assertIsNone(payload["controller"]["controller_id"])
        self.assertIsNone(payload["controller"]["track_id"])
        self.assertEqual(payload["controller"]["suspect_grace_ms"], 800)
        self.assertEqual(payload["controller"]["reacquire_timeout_ms"], 4000)
        self.assertNotIn("candidates", payload)
        self.assertNotIn("target_id", payload)

    def test_controller_session_accepts_recovery_states(self):
        store = self.client.app.state.control_store
        store.begin_session("controller-recovery-test", 100)
        store.update_controller("controller-recovery-test", "suspect", "person-1", 200)
        store.update_controller("controller-recovery-test", "reacquiring", "person-1", 1000)
        store.update_controller("controller-recovery-test", "locked", "person-3", 1100)

    def test_identity_and_manual_target_endpoints_are_removed(self):
        self.assertEqual(self.client.get("/api/identities").status_code, 404)
        self.assertEqual(self.client.patch("/api/target", json={"identity_id": None}).status_code, 404)

    def test_controller_can_be_unlocked_and_mappings_remain_available(self):
        self.assertEqual(self.client.post("/api/controller/unlock").json()["controller"]["state"], "unlocked")
        self.assertEqual(self.client.get("/api/mappings").status_code, 200)

    def test_recognition_confidence_setting_is_validated_and_applied(self):
        settings = self.client.get("/api/recognition-settings")
        self.assertEqual(settings.status_code, 200)
        self.assertEqual(settings.json()["gesture_confidence_threshold"], 0.6)
        updated = self.client.put(
            "/api/recognition-settings", json={"gesture_confidence_threshold": 0.65}
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["gesture_confidence_threshold"], 0.65)
        invalid = self.client.put(
            "/api/recognition-settings", json={"gesture_confidence_threshold": 0.63}
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            self.client.get("/api/recognition-settings").json()["gesture_confidence_threshold"], 0.65
        )
        status = self.client.get("/api/status").json()
        self.assertEqual(status["vision"]["confidence_threshold"], 0.65)

    def test_invalid_rtsp_address_does_not_echo_credentials(self):
        response = self.client.post(
            "/api/stream/start",
            json={"rtsp_url": "ftp://operator:s3cret@camera.local/live"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("operator", response.text)
        self.assertNotIn("s3cret", response.text)

    def test_home_is_the_promo_display_and_settings_are_separate(self):
        homepage = self.client.get("/").text
        settings = self.client.get("/settings").text
        self.assertIn("/media/promo.mp4", homepage)
        self.assertIn("playsinline loop controls", homepage)
        self.assertIn('href="/settings"', homepage)
        self.assertNotIn('target="_blank"', homepage)
        self.assertNotIn('id="rtspUrl"', homepage)
        self.assertNotIn('id="mappingGrid"', homepage)
        self.assertIn('id="rtspUrl"', settings)
        self.assertIn('id="mappingGrid"', settings)
        self.assertIn('id="gestureConfidenceRange"', settings)
        self.assertIn('step="0.05"', settings)

    def test_home_camera_placeholder_can_be_hidden_when_feed_is_ready(self):
        styles = self.client.get("/static/styles.css").text
        self.assertIn(".pip-placeholder[hidden]", styles)
        self.assertIn(".pip-placeholder[hidden] { display: none; }", styles)

    def test_html_and_static_resources_are_revalidated(self):
        for path in ("/", "/settings", "/static/app.js", "/static/styles.css"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response.headers.get("cache-control", ""))

    def test_promo_route_supports_byte_ranges(self):
        response = self.client.get("/media/promo.mp4", headers={"Range": "bytes=2-7"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers["content-range"], "bytes 2-7/18")
        self.assertEqual(response.content, b"st-vid")
        self.assertEqual(response.headers["accept-ranges"], "bytes")

    def test_homepage_mjpeg_visibility_does_not_depend_on_img_load_event(self):
        player = self.client.get("/static/player.js").text
        self.assertIn("const hasImage = streamReady && frameFresh && !feedFailed;", player)
        self.assertNotIn("naturalWidth", player)
        self.assertNotIn("feedLoaded", player)

    def test_mjpeg_parts_include_content_length(self):
        route = next(route for route in self.client.app.routes if getattr(route, "path", None) == "/video.mjpg")
        frame = b"\xff\xd8test-jpeg\xff\xd9"
        self.client.app.state.stream_manager._latest_jpeg = frame

        class ConnectedRequest:
            def __init__(self):
                self.checks = 0

            async def is_disconnected(self):
                self.checks += 1
                return self.checks > 1

        response = asyncio.run(route.endpoint(ConnectedRequest()))
        part = asyncio.run(response.body_iterator.__anext__())
        self.assertIn(b"Content-Type: image/jpeg\r\n", part)
        self.assertIn(f"Content-Length: {len(frame)}\r\n".encode("ascii"), part)
        self.assertTrue(part.endswith(frame + b"\r\n"))
        self.assertEqual(response.headers.get("x-accel-buffering"), "no")

    def test_mjpeg_route_starts_as_a_multipart_stream_without_a_camera(self):
        route = next(route for route in self.client.app.routes if getattr(route, "path", None) == "/video.mjpg")

        class DisconnectedRequest:
            async def is_disconnected(self):
                return True

        response = asyncio.run(route.endpoint(DisconnectedRequest()))
        self.assertEqual(
            response.headers["content-type"],
            "multipart/x-mixed-replace; boundary=frame",
        )
        with self.assertRaises(StopAsyncIteration):
            asyncio.run(response.body_iterator.__anext__())

    def test_workflow_crud_validation_dry_run_versions_and_trigger_conflict(self):
        workflow = new_workflow("展示欢迎画面")
        created = self.client.post("/api/workflows", json=workflow)
        self.assertEqual(created.status_code, 201, created.text)
        saved = created.json()["workflow"]
        workflow_id = saved["id"]
        self.assertEqual(saved["version"], 1)
        self.assertTrue(self.client.post(f"/api/workflows/{workflow_id}/validate").json()["valid"])

        dry_run = self.client.post(f"/api/workflows/{workflow_id}/dry-run", json={"context": {}})
        self.assertEqual(dry_run.status_code, 200, dry_run.text)
        self.assertEqual(dry_run.json()["run"]["status"], "success")
        self.assertEqual(dry_run.json()["run"]["mode"], "dry_run")
        self.assertTrue(all(step["status"] == "simulated" for step in dry_run.json()["run"]["steps"]))

        copied = self.client.post(f"/api/workflows/{workflow_id}/copy")
        self.assertEqual(copied.status_code, 201, copied.text)
        copy_id = copied.json()["workflow"]["id"]
        self.assertNotEqual(copy_id, workflow_id)
        self.assertFalse(copied.json()["workflow"]["enabled"])

        self.assertEqual(self.client.post(f"/api/workflows/{workflow_id}/enable").status_code, 200)
        self.assertEqual(self.client.post(f"/api/workflows/{copy_id}/enable").status_code, 409)
        updated = self.client.put(f"/api/workflows/{workflow_id}", json={**saved, "description": "更新"})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["workflow"]["version"], 3)
        self.assertEqual(len(self.client.get(f"/api/workflows/{workflow_id}/versions").json()["versions"]), 3)
        self.assertEqual(self.client.post(f"/api/workflows/{workflow_id}/disable").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/workflows/{workflow_id}").status_code, 200)

    def test_workflow_api_rejects_unregistered_actions_and_media_paths(self):
        workflow = new_workflow("无效动作")
        workflow["nodes"][0].update({"action": "video.load", "params": {"media_id": "..\\secret.mp4"}})
        response = self.client.post("/api/workflows", json=workflow)
        self.assertEqual(response.status_code, 400)
        self.assertIn("不是允许的选项", response.text)
        self.assertIn("video.load", {action["name"] for action in self.client.get("/api/actions").json()["actions"]})

    def test_pointer_mode_api_can_be_enabled_and_disabled(self):
        initial = self.client.get("/api/pointer/mode")
        self.assertEqual(initial.status_code, 200)
        self.assertFalse(initial.json()["enabled"])

        enabled = self.client.post("/api/pointer/mode", json={"enabled": True})
        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.json()["enabled"])
        self.assertTrue(self.client.get("/api/status").json()["pointer_mode_enabled"])

        disabled = self.client.post("/api/pointer/mode", json={"enabled": False})
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["enabled"])

    def test_workflow_routes_and_page_are_local_and_available(self):
        self.assertEqual(self.client.get("/workflows").status_code, 200)
        workflow_page = self.client.get("/workflows").text
        self.assertIn('id="pointerMode"', workflow_page)
        self.assertIn('id="pointerMirror"', workflow_page)
        self.assertIn("/api/workflows", self.client.get("/static/workflows.js").text)
        self.assertEqual(
            self.client.get("/api/media-assets").json()["media_assets"][0]["id"],
            "company-promo",
        )
        self.assertEqual(self.client.get("/api/presentations").json()["presentations"], [])


if __name__ == "__main__":
    unittest.main()
