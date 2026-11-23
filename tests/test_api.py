import asyncio
import tempfile
import unittest
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from app.display_pages import DISPLAY_PAGE_IDS
from app.main import create_app
from app.workflow import new_workflow
from app.controller import ControllerLock
from app.vision import VisionProcessor


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.promo_path = Path(self.temp_dir.name) / "promo.mp4"
        self.promo_path.write_bytes(b"test-video-content")
        self.database_path = Path(self.temp_dir.name) / "data.sqlite3"
        self.client = TestClient(create_app(self.database_path, self.promo_path))

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

    def test_status_endpoints_share_the_live_suspect_identity_snapshot(self):
        processor = VisionProcessor.__new__(VisionProcessor)
        processor.lock = threading.RLock()
        processor.controller = ControllerLock()
        processor.controller.observe_lock_candidates(["person-1"], 0)
        processor.controller.observe_lock_candidates(["person-1"], 50)
        processor.controller.update_tracking(set(), 100)
        manager = self.client.app.state.stream_manager
        manager._processor = processor
        try:
            for confirmed in (True, False, True):
                processor._suspect_identity_confirmed = confirmed
                for endpoint in ("/api/status", "/api/workflow-status"):
                    with self.subTest(confirmed=confirmed, endpoint=endpoint):
                        controller = self.client.get(endpoint).json()["controller"]
                        self.assertEqual(controller["state"], "suspect")
                        self.assertIs(controller["identity_confirmed"], confirmed)
            processor.controller.update_tracking(set(), 900)
            self.assertIs(self.client.get("/api/status").json()["controller"]["identity_confirmed"], False)
        finally:
            manager._processor = None

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

    def test_home_is_the_persistent_display_shell_and_settings_are_separate(self):
        homepage = self.client.get("/").text
        settings = self.client.get("/settings").text
        self.assertIn('id="displayPageFrame"', homepage)
        self.assertIn("/static/display-shell.js", homepage)
        self.assertNotIn("/media/promo.mp4", homepage)
        self.assertNotIn('id="rtspUrl"', homepage)
        self.assertNotIn('id="mappingGrid"', homepage)
        promo = self.client.get("/static/pages/promo.html").text
        self.assertIn("/media/promo.mp4", promo)
        self.assertIn("playsinline loop controls", promo)
        self.assertIn('href="/settings" target="gesture-control-admin"', homepage)
        self.assertIn('id="openManagement"', homepage)
        self.assertNotIn('href="/settings" target="_top"', promo)
        self.assertNotIn('target="_blank"', promo)
        self.assertIn('id="rtspUrl"', settings)
        self.assertNotIn('id="mappingGrid"', settings)
        self.assertIn('id="gestureConfidenceRange"', settings)
        self.assertIn('step="0.05"', settings)

    def test_display_page_registry_is_an_explicit_local_allowlist(self):
        response = self.client.get("/api/display/pages")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_page_id"], "promo")
        pages = payload["pages"]
        self.assertEqual([page["page_id"] for page in pages],
                         list(DISPLAY_PAGE_IDS))
        for page in pages:
            if page["page_type"] == "local":
                self.assertTrue(page["path"].startswith("/static/pages/"))
                self.assertEqual(self.client.get(page["path"]).status_code, 200)
                self.assertIsNone(page["url"])
            else:
                self.assertEqual(page["page_type"], "external")
                self.assertIsNone(page["path"])
                self.assertTrue(page["url"].startswith("https://www.zhcomking.com/"))
        actions = {item["name"]: item for item in self.client.get("/api/actions").json()["actions"]}
        self.assertIn("web.navigate_page", actions)
        self.assertEqual(actions["web.navigate_page"]["schema"]["properties"]["page_id"]["enum"],
                         list(DISPLAY_PAGE_IDS))

    def test_display_shell_keeps_its_channels_and_cleans_up_superseded_navigation(self):
        shell = self.client.get("/static/display-shell.js").text
        self.assertIn('new WebSocket(protocol + "//" + window.location.host + "/ws/display")', shell)
        self.assertIn('new WebSocket(protocol + "//" + window.location.host + "/ws/events")', shell)
        self.assertIn("defaultPageId = payload.default_page_id", shell)
        self.assertIn("function rejectPageReadyWaiter(reason)", shell)
        self.assertIn('rejectPageReadyWaiter("展示页面切换请求已被更新")', shell)
        self.assertIn('rejectPageReadyWaiter("展示控制中心已离开页面")', shell)
        self.assertIn('window.addEventListener("pageshow"', shell)
        self.assertIn("if (!event.persisted) return;", shell)
        self.assertIn("pendingPageCommands.delete(key)", shell)
        self.assertIn("resolvedPath.pathname !== page.path", shell)
        self.assertNotIn("ALLOWED_EXTERNAL_PAGE_URLS", shell)
        self.assertIn("function isPublicExternalHost(hostname)", shell)
        self.assertIn("function safeExternalPageUrl(page)", shell)
        self.assertIn("page.parent_id", shell)
        self.assertIn('case "web.navigate_parent"', shell)
        self.assertIn('pageType === "external"', shell)
        self.assertIn("handleExternalFrameLoad", shell)
        self.assertIn('elements.frame.referrerPolicy = "no-referrer"', shell)
        self.assertIn("visual_verification_required: pageType === \"external\"", shell)

        promo_script = self.client.get("/static/player.js").text
        registered_script = self.client.get("/static/display-page.js").text
        self.assertIn('page_id: "promo"', promo_script)
        self.assertIn('type: "display:ready"', promo_script)
        self.assertIn("page_id: pageId", registered_script)
        self.assertIn('type: "display:ready"', registered_script)

    def test_video_workflow_actions_include_incremental_volume_controls(self):
        actions = {
            item["name"]: item
            for item in self.client.get("/api/actions").json()["actions"]
        }
        self.assertIn("video.volume_up", actions)
        self.assertIn("video.volume_down", actions)
        self.assertFalse(actions["video.volume_up"]["idempotent"])
        self.assertFalse(actions["video.volume_down"]["idempotent"])
        self.assertEqual(actions["video.volume_up"]["schema"]["properties"], {})
        self.assertEqual(actions["video.volume_down"]["schema"]["properties"], {})

        player = self.client.get("/static/player.js").text
        self.assertIn('case "video.volume_up":', player)
        self.assertIn('case "video.volume_down":', player)
        self.assertIn("video.volume + 0.1", player)
        self.assertIn("video.volume - 0.1", player)

    def test_display_channel_requires_page_ready_before_workflow_control(self):
        initial = self.client.get("/api/workflow-status")
        self.assertEqual(initial.status_code, 200)
        self.assertFalse(initial.json()["display_connected"])
        self.assertFalse(initial.json()["display_ready"])
        self.assertIsNone(initial.json()["display_page_id"])
        self.assertIsNone(initial.json()["display_generation"])

        with self.client.websocket_connect(
            "/ws/display",
            headers={"origin": "http://127.0.0.1"},
        ) as websocket:
            connected = self.client.get("/api/workflow-status").json()
            self.assertTrue(connected["display_connected"])
            self.assertFalse(connected["display_ready"])

            websocket.send_json({
                "type": "display:ready",
                "page_id": "promo",
                "generation": 7,
            })
            ready = self.client.get("/api/workflow-status").json()
            self.assertTrue(ready["display_connected"])
            self.assertTrue(ready["display_ready"])
            self.assertEqual(ready["display_page_id"], "promo")
            self.assertEqual(ready["display_generation"], 7)

            websocket.send_json({
                "type": "display:loading",
                "page_id": "factory",
                "generation": 8,
            })
            loading = self.client.get("/api/workflow-status").json()
            self.assertTrue(loading["display_connected"])
            self.assertFalse(loading["display_ready"])
            self.assertIsNone(loading["display_page_id"])

    def test_display_shell_reports_page_readiness_to_backend(self):
        shell = self.client.get("/static/display-shell.js").text
        self.assertIn('function sendDisplayState(type, payload = {})', shell)
        self.assertIn('sendDisplayState("display:loading"', shell)
        self.assertIn('sendDisplayState("display:ready"', shell)
        self.assertIn('setShellStatus("connecting", "展示控制中心已连接 · 等待展示页面就绪")', shell)
        workflow_status = self.client.get("/api/workflow-status").json()
        self.assertIn("display_ready", workflow_status)
        self.assertIn("display_page_id", workflow_status)
        self.assertIn("display_generation", workflow_status)

    def test_external_display_page_crud_updates_live_action_schema(self):
        created = self.client.post("/api/display/pages", json={
            "page_id": "energy_storage", "title": "储能系列产品",
            "description": "康晋官网储能产品列表",
            "url": "https://www.zhcomking.com/products/storage.html",
            "parent_id": "company_website",
        })
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["page"]["parent_id"], "company_website")
        navigate = next(item for item in self.client.get("/api/actions").json()["actions"]
                        if item["name"] == "web.navigate_page")
        self.assertIn("energy_storage", navigate["schema"]["properties"]["page_id"]["enum"])
        self.assertEqual(
            navigate["schema"]["properties"]["page_id"]["enum_labels"]["energy_storage"],
            "康晋电气官方网站 / 储能系列产品",
        )
        self.assertIn("web.navigate_parent", {
            item["name"] for item in self.client.get("/api/actions").json()["actions"]
        })

        workflow = new_workflow("跳转储能子页面")
        workflow["nodes"][0].update({
            "action": "web.navigate_page", "params": {"page_id": "energy_storage"},
        })
        self.assertEqual(self.client.post("/api/workflows", json=workflow).status_code, 201)

        updated = self.client.put("/api/display/pages/energy_storage", json={
            "title": "储能产品目录",
            "url": "https://www.zhcomking.com/products/storage/index.html",
        })
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["page"]["title"], "储能产品目录")
        self.assertIn("energy_storage", [
            item["page_id"] for item in self.client.get("/api/display/pages").json()["pages"]
        ])
        blocked = self.client.delete("/api/display/pages/energy_storage")
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("工作流引用", blocked.text)

    def test_display_page_api_persists_custom_page_after_app_restart(self):
        created = self.client.post("/api/display/pages", json={
            "page_id": "restart_check", "title": "重启持久化验证",
            "url": "https://www.zhcomking.com/restart-check/",
            "parent_id": "company_website",
        })
        self.assertEqual(created.status_code, 201, created.text)

        self.client.close()
        self.client = TestClient(create_app(self.database_path, self.promo_path))
        payload = self.client.get("/api/display/pages?include_disabled=true").json()
        pages = {page["page_id"]: page for page in payload["pages"]}
        self.assertIn("restart_check", pages)
        self.assertEqual(pages["restart_check"]["url"], "https://www.zhcomking.com/restart-check/")
        self.assertEqual(pages["restart_check"]["parent_id"], "company_website")
        self.assertEqual(
            [page_id for page_id in ("promo", "factory", "product", "company_website") if page_id in pages],
            ["promo", "factory", "product", "company_website"],
        )

        updated = self.client.put("/api/display/pages/restart_check", json={
            "title": "重启后仍可编辑",
            "url": "https://www.zhcomking.com/restart-check/index.html",
        })
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["page"]["title"], "重启后仍可编辑")

        deleted = self.client.delete("/api/display/pages/restart_check")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        remaining = self.client.get("/api/display/pages?include_disabled=true").json()["pages"]
        self.assertNotIn("restart_check", {page["page_id"] for page in remaining})

    def test_display_page_api_rejects_parent_cycles_and_protects_parent_children(self):
        root = self.client.post("/api/display/pages", json={
            "page_id": "cycle_root", "title": "层级根页面",
            "url": "https://www.zhcomking.com/catalog/",
            "parent_id": "company_website",
        })
        self.assertEqual(root.status_code, 201, root.text)
        child = self.client.post("/api/display/pages", json={
            "page_id": "cycle_child", "title": "层级子页面",
            "url": "https://www.zhcomking.com/catalog/product/",
            "parent_id": "cycle_root",
        })
        self.assertEqual(child.status_code, 201, child.text)

        cycle = self.client.put("/api/display/pages/cycle_root", json={
            "parent_id": "cycle_child",
        })
        self.assertEqual(cycle.status_code, 400)
        self.assertIn("循环", cycle.text)

        blocked_delete = self.client.delete("/api/display/pages/cycle_root")
        self.assertEqual(blocked_delete.status_code, 409)
        blocked_disable = self.client.put("/api/display/pages/cycle_root", json={"enabled": False})
        self.assertEqual(blocked_disable.status_code, 400)

        self.assertEqual(self.client.delete("/api/display/pages/cycle_child").status_code, 200)
        self.assertEqual(self.client.delete("/api/display/pages/cycle_root").status_code, 200)

    def test_display_page_manager_ui_shows_hierarchy_and_accurate_access_states(self):
        page = self.client.get("/display-pages")
        self.assertEqual(page.status_code, 200)
        self.assertIn('href="/display-pages"', self.client.get("/settings").text)
        self.assertIn('id="pageUrl"', page.text)
        self.assertIn('id="pageParent"', page.text)
        self.assertIn('id="pageEnabled"', page.text)
        self.assertIn("网页目录与访问状态", page.text)
        self.assertIn("嵌入兼容性待现场验证", page.text)
        script = self.client.get("/static/display-pages.js").text
        self.assertIn("工作流可调用", script)
        self.assertIn("工作流不可调用", script)
        self.assertIn("(page.enabled || page.page_id === selectedId)", script)
        self.assertIn("option.disabled = !page.enabled", script)
        self.assertIn("仅保留当前父级关系", script)

    def test_display_page_manager_preserves_disabled_parent_and_child_host_invariant(self):
        parent = self.client.post("/api/display/pages", json={
            "page_id": "disabled_parent", "title": "可停用父页面",
            "url": "https://www.zhcomking.com/catalog/",
        })
        self.assertEqual(parent.status_code, 201, parent.text)
        child = self.client.post("/api/display/pages", json={
            "page_id": "disabled_child", "title": "可停用子页面",
            "url": "https://www.zhcomking.com/catalog/product/",
            "parent_id": "disabled_parent",
        })
        self.assertEqual(child.status_code, 201, child.text)

        self.assertEqual(
            self.client.put("/api/display/pages/disabled_child", json={"enabled": False}).status_code,
            200,
        )
        self.assertEqual(
            self.client.put("/api/display/pages/disabled_parent", json={"enabled": False}).status_code,
            200,
        )

        edited = self.client.put("/api/display/pages/disabled_child", json={
            "title": "编辑后仍保留父级",
            "url": "https://www.zhcomking.com/catalog/product-v2/",
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["page"]["parent_id"], "disabled_parent")
        self.assertFalse(edited.json()["page"]["enabled"])

        invalid_reparent = self.client.put("/api/display/pages/disabled_child", json={
            "parent_id": "disabled_parent",
            "enabled": True,
        })
        self.assertEqual(invalid_reparent.status_code, 400)
        self.assertIn("父页面必须处于启用状态", invalid_reparent.text)

        invalid_parent_host_change = self.client.put("/api/display/pages/disabled_parent", json={
            "url": "https://example.org/catalog/",
        })
        self.assertEqual(invalid_parent_host_change.status_code, 400)
        self.assertIn("子页面", invalid_parent_host_change.text)

    def test_display_page_url_validation_rejects_unsafe_destinations(self):
        invalid_urls = [
            "http://example.com/", "https://user:password@example.com/",
            "https://127.0.0.1/", "https://router.local/", "https://example.com:8443/",
        ]
        for url in invalid_urls:
            response = self.client.post("/api/display/pages/validate-url", json={"url": url})
            self.assertEqual(response.status_code, 400, url)
        valid = self.client.post("/api/display/pages/validate-url", json={
            "url": "https://WWW.ZHCOMKING.COM:443/products/"
        })
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(valid.json()["url"], "https://www.zhcomking.com/products/")

    def test_external_child_page_must_share_parent_host(self):
        response = self.client.post("/api/display/pages", json={
            "page_id": "wrong_host_child", "title": "错误域名子页面",
            "url": "https://example.org/products/", "parent_id": "company_website",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("同一个域名", response.text)

    def test_disabled_display_page_is_removed_from_navigation_schema(self):
        created = self.client.post("/api/display/pages", json={
            "page_id": "temporary_page", "title": "临时页面",
            "url": "https://www.zhcomking.com/temporary/",
            "parent_id": "company_website",
        })
        self.assertEqual(created.status_code, 201, created.text)
        disabled = self.client.put("/api/display/pages/temporary_page", json={"enabled": False})
        self.assertEqual(disabled.status_code, 200, disabled.text)
        action = next(item for item in self.client.get("/api/actions").json()["actions"]
                      if item["name"] == "web.navigate_page")
        self.assertNotIn("temporary_page", action["schema"]["properties"]["page_id"]["enum"])

    def test_default_display_page_can_be_changed_only_to_enabled_page(self):
        response = self.client.post("/api/display/default", json={"page_id": "company_website"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/api/display/pages").json()["default_page_id"], "company_website")

        local_default = self.client.post("/api/display/default", json={"page_id": "promo"})
        self.assertEqual(local_default.status_code, 200, local_default.text)
        self.assertEqual(self.client.get("/api/display/pages").json()["default_page_id"], "promo")

        response = self.client.post("/api/display/default", json={"page_id": "company_website"})
        self.assertEqual(response.status_code, 200, response.text)
        invalid = self.client.post("/api/display/default", json={"page_id": "missing"})
        self.assertEqual(invalid.status_code, 400)
        disabled_default = self.client.put(
            "/api/display/pages/company_website", json={"enabled": False}
        )
        self.assertEqual(disabled_default.status_code, 400)

    def test_display_page_management_ui_is_served(self):
        page = self.client.get("/display-pages")
        self.assertEqual(page.status_code, 200)
        self.assertIn("展示网页管理", page.text)
        self.assertIn("/static/display-pages.js", page.text)
        self.assertIn("/static/display-pages.css", page.text)
        self.assertEqual(self.client.get("/static/display-pages.js").status_code, 200)
        self.assertEqual(self.client.get("/static/display-pages.css").status_code, 200)

    def test_workflow_creation_does_not_require_camera_stream(self):
        self.assertEqual(self.client.get("/api/status").json()["state"], "stopped")
        workflow = new_workflow("离线编排工作流")
        response = self.client.post("/api/workflows", json=workflow)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["workflow"]["name"], "离线编排工作流")

    def test_workflow_rejects_unregistered_display_page_ids(self):
        workflow = new_workflow("无效展示页面")
        workflow["nodes"][0].update({
            "action": "web.navigate_page",
            "params": {"page_id": "external-url"},
        })
        response = self.client.post("/api/workflows", json=workflow)
        self.assertEqual(response.status_code, 400)
        self.assertIn("不是允许的选项", response.text)

    def test_home_camera_placeholder_can_be_hidden_when_feed_is_ready(self):
        styles = self.client.get("/static/styles.css").text
        self.assertIn(".pip-placeholder[hidden]", styles)
        self.assertIn(".pip-placeholder[hidden] { display: none; }", styles)

    def test_html_and_static_resources_are_revalidated(self):
        for path in ("/", "/settings", "/workflows", "/display-pages", "/static/app.js",
                     "/static/styles.css", "/static/display-shell.js", "/static/display-pages.js",
                     "/static/display-pages.css", "/static/pages/promo.html"):
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

    def test_page_scoped_gesture_workflows_can_share_gestures_across_pages(self):
        global_workflow = new_workflow("全局张开手掌")
        global_workflow["trigger"] = {
            "type": "gesture_trigger", "gesture": "Open_Palm", "page_scope": "global",
        }
        global_created = self.client.post("/api/workflows", json=global_workflow)
        self.assertEqual(global_created.status_code, 201, global_created.text)
        global_id = global_created.json()["workflow"]["id"]
        self.assertEqual(self.client.post(f"/api/workflows/{global_id}/enable").status_code, 200)

        promo_workflow = new_workflow("宣传片张开手掌")
        promo_workflow["trigger"] = {
            "type": "gesture_trigger", "gesture": "Open_Palm", "page_scope": "promo",
        }
        promo_created = self.client.post("/api/workflows", json=promo_workflow)
        self.assertEqual(promo_created.status_code, 201, promo_created.text)
        promo_id = promo_created.json()["workflow"]["id"]
        self.assertEqual(self.client.post(f"/api/workflows/{promo_id}/enable").status_code, 200)

        factory_workflow = new_workflow("工厂张开手掌")
        factory_workflow["trigger"] = {
            "type": "gesture_trigger", "gesture": "Open_Palm", "page_scope": "factory",
        }
        factory_created = self.client.post("/api/workflows", json=factory_workflow)
        self.assertEqual(factory_created.status_code, 201, factory_created.text)
        factory_id = factory_created.json()["workflow"]["id"]
        self.assertEqual(self.client.post(f"/api/workflows/{factory_id}/enable").status_code, 200)

        duplicate = new_workflow("重复宣传片手势")
        duplicate["trigger"] = {
            "type": "gesture_trigger", "gesture": "Open_Palm", "page_scope": "promo",
        }
        duplicate_created = self.client.post("/api/workflows", json=duplicate)
        self.assertEqual(duplicate_created.status_code, 201, duplicate_created.text)
        duplicate_id = duplicate_created.json()["workflow"]["id"]
        self.assertEqual(self.client.post(f"/api/workflows/{duplicate_id}/enable").status_code, 409)

        factory_saved = self.client.get(f"/api/workflows/{factory_id}").json()["workflow"]
        factory_saved["trigger"]["page_scope"] = "promo"
        conflict_update = self.client.put(f"/api/workflows/{factory_id}", json=factory_saved)
        self.assertEqual(conflict_update.status_code, 409)

        invalid_scope = new_workflow("未登记主页")
        invalid_scope["trigger"]["page_scope"] = "not-registered"
        invalid_response = self.client.post("/api/workflows", json=invalid_scope)
        self.assertEqual(invalid_response.status_code, 400)
        self.assertIn("适用主页未登记", invalid_response.text)

    def test_display_page_cannot_be_deleted_while_a_gesture_scope_references_it(self):
        created = self.client.post("/api/display/pages", json={
            "page_id": "gesture_scope_page",
            "title": "手势作用域测试页",
            "url": "https://www.zhcomking.com/gesture-scope/",
            "parent_id": "company_website",
        })
        self.assertEqual(created.status_code, 201, created.text)

        workflow = new_workflow("页面作用域引用")
        workflow["trigger"]["page_scope"] = "gesture_scope_page"
        saved = self.client.post("/api/workflows", json=workflow)
        self.assertEqual(saved.status_code, 201, saved.text)

        blocked = self.client.delete("/api/display/pages/gesture_scope_page")
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("手势工作流适用范围", blocked.text)

    def test_workflow_api_rejects_unregistered_actions_and_media_paths(self):
        workflow = new_workflow("无效动作")
        workflow["nodes"][0].update({"action": "video.load", "params": {"media_id": "..\\secret.mp4"}})
        response = self.client.post("/api/workflows", json=workflow)
        self.assertEqual(response.status_code, 400)
        self.assertIn("不是允许的选项", response.text)
        self.assertIn("video.load", {action["name"] for action in self.client.get("/api/actions").json()["actions"]})

    def test_pointer_settings_api_persists_partial_updates_and_rejects_invalid_thresholds(self):
        initial = self.client.get("/api/pointer/settings")
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["press_stable_frames"], 2)
        updated = self.client.put("/api/pointer/settings", json={"min_cutoff": 1.7, "press_stable_frames": 3})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["min_cutoff"], 1.7)
        self.assertEqual(updated.json()["press_stable_frames"], 3)
        self.assertEqual(updated.json()["release_threshold"], 0.5)
        invalid = self.client.put("/api/pointer/settings", json={"press_threshold": 0.7, "release_threshold": 0.6})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.client.get("/api/pointer/settings").json()["min_cutoff"], 1.7)

    def test_pointer_settings_api_rejects_unknown_boolean_and_fractional_integer_values(self):
        unknown = self.client.put("/api/pointer/settings", json={"unknown_option": 1})
        self.assertEqual(unknown.status_code, 422)
        boolean = self.client.put("/api/pointer/settings", json={"beta": True})
        self.assertEqual(boolean.status_code, 422)
        fractional = self.client.put("/api/pointer/settings", json={"press_stable_frames": 2.5})
        self.assertEqual(fractional.status_code, 422)
        self.assertEqual(self.client.get("/api/pointer/settings").json()["press_stable_frames"], 2)

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
        self.assertIn('id="workflowList"', workflow_page)
        self.assertIn('id="workflowGeneratorApiKey"', workflow_page)
        self.assertIn("/static/pointer-event-buffer.js?v=20261118-workflow-fix-1", workflow_page)
        self.assertIn("/static/workflows.js?v=20261123-layout-2", workflow_page)
        self.assertIn("/static/workflows.css?v=20261123-layout-2", workflow_page)
        self.assertIn("/api/workflows", self.client.get("/static/workflows.js").text)
        self.assertEqual(
            self.client.get("/api/media-assets").json()["media_assets"][0]["id"],
            "company-promo",
        )
        self.assertEqual(self.client.get("/api/presentations").json()["presentations"], [])


if __name__ == "__main__":
    unittest.main()
