import asyncio
import unittest

from app.display import DisplayCommandChannel


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.closed = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=None, reason=None):
        self.closed = True

    async def send_json(self, payload):
        self.sent.append(payload)


class DisplayCommandChannelTests(unittest.TestCase):
    def test_connection_and_page_readiness_are_separate_states(self):
        async def scenario():
            channel = DisplayCommandChannel()
            websocket = FakeWebSocket()
            connection_events = []
            ready_events = []
            channel.on_state_change = connection_events.append
            channel.on_ready_change = ready_events.append

            self.assertTrue(await channel.connect(websocket))
            self.assertTrue(channel.connected)
            self.assertFalse(channel.ready)
            self.assertEqual(connection_events, [True])
            self.assertEqual(ready_events, [])

            await channel.receive(websocket, {
                "type": "display:ready",
                "page_id": "promo",
                "generation": 1,
            })
            self.assertTrue(channel.connected)
            self.assertTrue(channel.ready)
            self.assertEqual(channel.ready_page_id, "promo")
            self.assertEqual(channel.ready_generation, 1)
            self.assertEqual(ready_events, [True])

            await channel.receive(websocket, {
                "type": "display:loading",
                "page_id": "factory",
                "generation": 2,
            })
            self.assertTrue(channel.connected)
            self.assertFalse(channel.ready)
            self.assertEqual(connection_events, [True])
            self.assertEqual(ready_events, [True, False])

            await channel.receive(websocket, {
                "type": "display:ready",
                "page_id": "factory",
                "generation": 2,
            })
            self.assertTrue(channel.ready)
            self.assertEqual(channel.ready_page_id, "factory")
            self.assertEqual(channel.ready_generation, 2)

            await channel.disconnect(websocket)
            self.assertFalse(channel.connected)
            self.assertFalse(channel.ready)
            self.assertEqual(connection_events, [True, False])

        asyncio.run(scenario())

    def test_execute_waits_for_page_ready_and_resumes_after_navigation(self):
        async def scenario():
            channel = DisplayCommandChannel()
            websocket = FakeWebSocket()
            await channel.connect(websocket)

            command = {
                "run_id": "run-1",
                "command_id": "command-1",
                "action": "web.set_scene",
                "params": {"scene": "factory_intro"},
            }
            task = asyncio.create_task(channel.execute(command, 1000))
            await asyncio.sleep(0)
            self.assertEqual(websocket.sent, [])

            await channel.receive(websocket, {
                "type": "display:ready",
                "page_id": "factory",
                "generation": 3,
            })
            await asyncio.sleep(0)
            self.assertEqual(len(websocket.sent), 1)
            self.assertEqual(websocket.sent[0]["type"], "command")
            self.assertEqual(websocket.sent[0]["command_id"], "command-1")

            await channel.receive(websocket, {
                "type": "ack",
                "run_id": "run-1",
                "command_id": "command-1",
                "success": True,
                "result": {"updated": True},
            })
            self.assertEqual(await task, {"updated": True})
        asyncio.run(scenario())

