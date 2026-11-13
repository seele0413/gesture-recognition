import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.action_engine import ActionRegistry, WorkflowEngine
from app.database import ControlStore
from app.display import DisplayCommandChannel
from app.ppt_actions import PresentationAdapter
from app.video_actions import register_video_actions
from app.workflow import new_workflow
from app.workflow_validator import validate_workflow
from app.web_actions import BrowserCommandAdapter


class WorkflowValidatorTests(unittest.TestCase):
    def setUp(self):
        self.registry = ActionRegistry()
        self.registry.register(
            "test.record", properties={"value": {"type": "integer", "minimum": 0, "maximum": 10}},
            required=["value"], handler=lambda _params, _context: {"ok": True}, idempotent=True,
        )

    def test_default_workflow_is_valid_against_registry(self):
        workflow = new_workflow()
        schemas = {"video.play": {"properties": {}, "required": [], "idempotent": True}}
        self.assertEqual(validate_workflow(workflow, schemas), [])

    def test_rejects_duplicate_ids_cycles_unknown_actions_and_bad_parameters(self):
        workflow = new_workflow()
        workflow["nodes"] = [
            {"id": "a", "type": "action", "action": "test.record", "params": {"value": "3"}},
            {"id": "a", "type": "end", "params": {}},
        ]
        workflow["edges"] = [{"source": "a", "target": "missing"}]
        errors = validate_workflow(workflow, self.registry.schema_map())
        self.assertGreaterEqual(len(errors), 5)

    def test_rejects_retry_for_non_idempotent_action(self):
        self.registry.register("test.advance", properties={}, required=[], handler=lambda _p, _c: None, idempotent=False)
        workflow = new_workflow()
        workflow["nodes"][0].update({"action": "test.advance", "retries": 1})
        self.assertTrue(any("不能自动重试" in error for error in validate_workflow(workflow, self.registry.schema_map())))

    def test_condition_requires_explicit_true_and_false_edges(self):
        workflow = new_workflow()
        workflow["nodes"] = [
            {"id": "condition", "type": "condition", "params": {"field": "confidence", "operator": "gte", "value": 0.6}},
            {"id": "yes", "type": "end", "params": {}},
            {"id": "no", "type": "end", "params": {}},
        ]
        workflow["edges"] = [
            {"source": "condition", "target": "yes", "when": "true"},
            {"source": "condition", "target": "no", "when": "false"},
        ]
        self.assertEqual(validate_workflow(workflow, self.registry.schema_map()), [])

    def test_malformed_unhashable_fields_are_rejected_without_crashing(self):
        workflow = new_workflow()
        workflow["nodes"][0]["type"] = []
        workflow["edges"] = [{"source": [], "target": "end"}]
        self.assertTrue(validate_workflow(workflow, self.registry.schema_map()))


class WorkflowEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ControlStore(Path(self.temp_dir.name) / "workflow.sqlite3")
        self.calls = []
        self.actions = ActionRegistry()

        async def record(params, context):
            self.calls.append((params["value"], context["run_id"], context["command_id"]))
            return {"recorded": params["value"]}

        self.actions.register(
            "test.record", properties={"value": {"type": "integer", "minimum": 0, "maximum": 10}},
            required=["value"], handler=record, idempotent=True,
        )
        self.engine = WorkflowEngine(self.store, self.actions)
        self.engine.set_display_connected(True)
        await self.engine.on_event({"type": "controller", "state": "locked", "track_id": "person-a"})

    async def asyncTearDown(self):
        await self.engine.close()
        self.temp_dir.cleanup()

    def _workflow(self, action_count=5, *, trigger=None):
        workflow = new_workflow("sequence")
        workflow["trigger"] = trigger or {"type": "gesture_trigger", "gesture": "Open_Palm"}
        nodes = []
        edges = []
        for index in range(action_count):
            node_id = f"action-{index}"
            nodes.append({
                "id": node_id, "type": "action", "action": "test.record", "params": {"value": index},
                "timeout_ms": 1000, "on_error": "stop",
            })
            if index:
                edges.append({"source": f"action-{index - 1}", "target": node_id})
        nodes.append({"id": "end", "type": "end", "params": {}})
        edges.append({"source": f"action-{action_count - 1}", "target": "end"})
        workflow["nodes"] = nodes
        workflow["edges"] = edges
        workflow["enabled"] = True
        return workflow

    async def _trigger(self, target="person-a", gesture="Open_Palm", timestamp=100):
        return await self.engine.on_event({
            "type": "gesture", "gesture": gesture, "target_id": target,
            "action_triggered": True, "action": "play_pause", "confidence": 0.9,
            "handedness": "Right", "timestamp_ms": timestamp,
        })

    async def test_one_confirmed_master_gesture_runs_five_sequential_actions(self):
        workflow = self.store.save_workflow(self._workflow())
        event = await self._trigger()
        self.assertTrue(event["workflow_handled"])
        await self.engine._active_task
        self.assertEqual([item[0] for item in self.calls], list(range(5)))
        run = self.store.get_workflow_runs()[0]
        self.assertEqual(run["status"], "success")
        self.assertEqual(len(self.store.get_workflow_run(run["run_id"])["steps"]), 5)
        self.assertEqual({item[1] for item in self.calls}, {run["run_id"]})
        self.assertEqual(len({item[2] for item in self.calls}), 5)
        self.assertEqual(workflow["version"], 1)

    async def test_unlocked_or_different_person_cannot_trigger(self):
        workflow = self.store.save_workflow(self._workflow())
        other = await self._trigger(target="person-b")
        self.assertIsNone(other)
        await self.engine.on_event({"type": "controller", "state": "unlocked", "track_id": None})
        self.assertIsNone(await self._trigger(timestamp=101))
        self.assertEqual(self.store.get_workflow_runs(), [])
        self.assertEqual(self.calls, [])

    async def test_master_loss_cancels_remaining_steps(self):
        workflow = self._workflow(action_count=1)
        workflow["nodes"].insert(0, {"id": "wait", "type": "delay", "params": {"delay_ms": 10000}})
        workflow["edges"] = [{"source": "wait", "target": "action-0"}, {"source": "action-0", "target": "end"}]
        self.store.save_workflow(workflow)
        await self._trigger()
        await asyncio.sleep(0)
        await self.engine.on_event({"type": "controller", "state": "lost", "track_id": "person-a"})
        await self.engine._active_task
        self.assertEqual(self.store.get_workflow_runs()[0]["status"], "cancelled")
        self.assertEqual(self.calls, [])

    async def test_display_disconnect_cancels_run_and_pauses_new_triggers(self):
        workflow = self._workflow(action_count=1)
        workflow["nodes"].insert(0, {"id": "wait", "type": "delay", "params": {"delay_ms": 10000}})
        workflow["edges"] = [{"source": "wait", "target": "action-0"}, {"source": "action-0", "target": "end"}]
        self.store.save_workflow(workflow)
        await self._trigger(timestamp=100)
        await asyncio.sleep(0)
        self.engine.set_display_connected(False)
        await self.engine._active_task
        self.assertEqual(self.store.get_workflow_runs()[0]["status"], "cancelled")
        self.assertEqual(self.calls, [])
        paused = await self._trigger(timestamp=200)
        self.assertTrue(paused["workflow_handled"])

    async def test_sequence_trigger_runs_only_after_complete_sequence(self):
        workflow = self._workflow(action_count=1, trigger={
            "type": "gesture_sequence_trigger", "gestures": ["Open_Palm", "Victory"], "sequence_window_ms": 5000,
        })
        self.store.save_workflow(workflow)
        first = await self._trigger(gesture="Open_Palm", timestamp=100)
        self.assertIsNone(first)
        self.assertIsNone(self.engine._active_task)
        second = await self._trigger(gesture="Victory", timestamp=200)
        self.assertTrue(second["workflow_handled"])
        await self.engine._active_task
        self.assertEqual(len(self.calls), 1)

    async def test_incomplete_sequence_does_not_replace_legacy_player_mapping(self):
        workflow = self._workflow(action_count=1, trigger={
            "type": "gesture_sequence_trigger", "gestures": ["Open_Palm", "Victory"], "sequence_window_ms": 5000,
        })
        self.store.save_workflow(workflow)
        self.assertIsNone(await self._trigger(gesture="Open_Palm", timestamp=100))
        self.assertIsNone(self.engine._active_task)

    async def test_dry_run_records_nodes_without_calling_actions(self):
        workflow = self._workflow(action_count=5)
        result = await self.engine.dry_run(workflow, {"confidence": 0.9})
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["steps"]), 5)
        self.assertTrue(all(step["status"] == "simulated" for step in result["steps"]))
        self.assertEqual(self.calls, [])

    async def test_workflow_with_same_trigger_is_not_started_concurrently(self):
        workflow = self._workflow(action_count=1)
        workflow["nodes"].insert(0, {"id": "wait", "type": "delay", "params": {"delay_ms": 300}})
        workflow["edges"] = [{"source": "wait", "target": "action-0"}, {"source": "action-0", "target": "end"}]
        self.store.save_workflow(workflow)
        await self._trigger(timestamp=100)
        run_id = self.engine._active_run_id
        await self._trigger(timestamp=200)
        self.assertEqual(self.engine._active_run_id, run_id)
        await self.engine._active_task
        self.assertEqual(len(self.calls), 1)

    async def test_action_timeout_is_recorded_as_timeout_and_stops_following_nodes(self):
        async def slow(_params, _context):
            await asyncio.sleep(1)

        self.actions.register("test.slow", properties={}, required=[], handler=slow, idempotent=False)
        workflow = self._workflow(action_count=1)
        workflow["nodes"][0].update({"action": "test.slow", "params": {}, "timeout_ms": 100})
        self.store.save_workflow(workflow)
        await self._trigger()
        await self.engine._active_task
        run = self.store.get_workflow_run(self.store.get_workflow_runs()[0]["run_id"])
        self.assertEqual(run["status"], "timeout")
        self.assertEqual(run["steps"][0]["status"], "timeout")
        self.assertEqual(self.calls, [])

    async def test_condition_and_error_branches_run_only_the_selected_path(self):
        def fail(_params, _context):
            raise RuntimeError("expected failure")

        self.actions.register("test.fail", properties={}, required=[], handler=fail, idempotent=False)
        workflow = new_workflow("branches")
        workflow["enabled"] = True
        workflow["nodes"] = [
            {"id": "condition", "type": "condition", "params": {"field": "confidence", "operator": "gte", "value": 0.8}},
            {"id": "fail", "type": "action", "action": "test.fail", "params": {}, "on_error": "branch", "timeout_ms": 1000},
            {"id": "normal", "type": "action", "action": "test.record", "params": {"value": 3}, "on_error": "stop", "timeout_ms": 1000},
            {"id": "end-error", "type": "end", "params": {}},
            {"id": "end-normal", "type": "end", "params": {}},
        ]
        workflow["edges"] = [
            {"source": "condition", "target": "fail", "when": "true"},
            {"source": "condition", "target": "normal", "when": "false"},
            {"source": "fail", "target": "end-normal"},
            {"source": "fail", "target": "end-error", "when": "error"},
            {"source": "normal", "target": "end-normal"},
        ]
        self.store.save_workflow(workflow)
        self.assertEqual(self.engine.validate(workflow), [])
        await self._trigger()
        await self.engine._active_task
        run = self.store.get_workflow_run(self.store.get_workflow_runs()[0]["run_id"])
        self.assertEqual(run["status"], "success")
        self.assertEqual([step["node_id"] for step in run["steps"]], ["condition", "fail"])
        self.assertEqual(self.calls, [])

    async def test_missing_registered_video_fails_before_following_action(self):
        asset_root = Path(self.temp_dir.name) / "media"
        asset_root.mkdir()
        self.store.sync_media_assets({"missing-video": {"title": "Missing", "filename": "missing.mp4"}})
        with patch("app.database.MEDIA_DIR", asset_root):
            registry = ActionRegistry()
            register_video_actions(registry, self.store, BrowserCommandAdapter(DisplayCommandChannel()))
            registry.register(
                "test.record", properties={"value": {"type": "integer", "minimum": 0, "maximum": 10}},
                required=["value"], handler=lambda params, _context: self.calls.append((params["value"],)), idempotent=True,
            )
            engine = WorkflowEngine(self.store, registry)
            engine.set_display_connected(True)
            await engine.on_event({"type": "controller", "state": "locked", "track_id": "person-a"})
            workflow = self._workflow(action_count=1)
            workflow["nodes"] = [
                {"id": "load", "type": "action", "action": "video.load", "params": {"media_id": "missing-video"}, "on_error": "stop", "timeout_ms": 1000},
                {"id": "next", "type": "action", "action": "test.record", "params": {"value": 1}, "on_error": "stop", "timeout_ms": 1000},
                {"id": "end", "type": "end", "params": {}},
            ]
            workflow["edges"] = [{"source": "load", "target": "next"}, {"source": "next", "target": "end"}]
            workflow["enabled"] = True
            self.assertEqual(engine.validate(workflow), [])
            self.store.save_workflow(workflow)
            await engine.on_event({
                "type": "gesture", "gesture": "Open_Palm", "target_id": "person-a", "action_triggered": True,
                "confidence": 0.9, "handedness": "Right", "action": "play_pause", "timestamp_ms": 100,
            })
            await engine._active_task
            run = self.store.get_workflow_run(self.store.get_workflow_runs()[0]["run_id"])
            self.assertEqual(run["status"], "failed")
            self.assertEqual([step["node_id"] for step in run["steps"]], ["load"])
            self.assertEqual(self.calls, [])
            await engine.close()

    async def test_powerpoint_unavailable_returns_clear_error(self):
        deck_path = Path(self.temp_dir.name) / "demo.pptx"
        deck_path.write_bytes(b"test")
        self.store.sync_presentation_decks({"demo": {"title": "Demo", "path": str(deck_path)}})
        adapter = PresentationAdapter(self.store)
        try:
            with patch.dict(sys.modules, {"pythoncom": None, "win32com": None}):
                with self.assertRaisesRegex(RuntimeError, "PowerPoint 控制不可用"):
                    await adapter.execute("ppt.open_deck", {"deck_id": "demo"}, {})
        finally:
            await adapter.close()


class _FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = None

    async def accept(self):
        return None

    async def close(self, code, reason):
        self.closed = (code, reason)

    async def send_json(self, message):
        self.sent.append(message)


class DisplayCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_waits_for_matching_ack_and_rejects_second_client(self):
        channel = DisplayCommandChannel()
        socket = _FakeSocket()
        self.assertTrue(await channel.connect(socket))
        rejected = _FakeSocket()
        self.assertFalse(await channel.connect(rejected))
        self.assertEqual(rejected.closed[0], 1013)
        command = {"run_id": "run-1", "command_id": "command-1", "action": "video.play", "params": {}}
        pending = asyncio.create_task(channel.execute(command, 1000))
        await asyncio.sleep(0)
        self.assertEqual(socket.sent[0]["command_id"], "command-1")
        await channel.receive(socket, {
            "type": "ack", "run_id": "run-1", "command_id": "command-1", "success": True,
            "result": {"paused": False},
        })
        self.assertEqual(await pending, {"paused": False})
        await channel.disconnect(socket)
        self.assertFalse(channel.connected)

    async def test_disconnect_fails_pending_command(self):
        channel = DisplayCommandChannel()
        socket = _FakeSocket()
        await channel.connect(socket)
        pending = asyncio.create_task(channel.execute({"run_id": "r", "command_id": "c"}, 1000))
        await asyncio.sleep(0)
        await channel.disconnect(socket)
        with self.assertRaises(ConnectionError):
            await pending


if __name__ == "__main__":
    unittest.main()
