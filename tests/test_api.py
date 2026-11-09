import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


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
        self.assertNotIn("candidates", payload)
        self.assertNotIn("target_id", payload)

    def test_identity_and_manual_target_endpoints_are_removed(self):
        self.assertEqual(self.client.get("/api/identities").status_code, 404)
        self.assertEqual(self.client.patch("/api/target", json={"identity_id": None}).status_code, 404)

    def test_controller_can_be_unlocked_and_mappings_remain_available(self):
        self.assertEqual(self.client.post("/api/controller/unlock").json()["controller"]["state"], "unlocked")
        self.assertEqual(self.client.get("/api/mappings").status_code, 200)

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


if __name__ == "__main__":
    unittest.main()
