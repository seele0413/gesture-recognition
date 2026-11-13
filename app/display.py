from __future__ import annotations

import asyncio
from typing import Any
from typing import Callable

from fastapi import WebSocket


class DisplayCommandChannel:
    """A single active browser executor with command-id matched acknowledgements."""

    def __init__(self) -> None:
        self._active: WebSocket | None = None
        self._lock = asyncio.Lock()
        self._pending: dict[str, tuple[str, asyncio.Future]] = {}
        self.on_state_change: Callable[[bool], None] | None = None

    @property
    def connected(self) -> bool:
        return self._active is not None

    async def connect(self, websocket: WebSocket) -> bool:
        async with self._lock:
            if self._active is not None:
                await websocket.close(code=1013, reason="display client already connected")
                return False
            await websocket.accept()
            self._active = websocket
        if self.on_state_change:
            self.on_state_change(True)
        return True

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if self._active is not websocket:
                return
            self._active = None
            pending = [future for _run_id, future in self._pending.values()]
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(ConnectionError("展示执行客户端已断开"))
        if self.on_state_change:
            self.on_state_change(False)

    async def receive(self, websocket: WebSocket, message: Any) -> None:
        if websocket is not self._active or not isinstance(message, dict) or message.get("type") != "ack":
            return
        command_id = message.get("command_id")
        run_id = message.get("run_id")
        pending = self._pending.get(command_id) if isinstance(command_id, str) else None
        if not pending or pending[0] != run_id:
            return
        future = pending[1]
        self._pending.pop(command_id, None)
        if future.done():
            return
        if not isinstance(message.get("success"), bool):
            future.set_exception(ValueError("展示客户端返回了无效确认"))
        elif not message["success"]:
            error = message.get("error")
            future.set_exception(RuntimeError(str(error)[:300] if error else "展示客户端动作失败"))
        else:
            result = message.get("result", {})
            future.set_result(result if isinstance(result, dict) else {"value": result})

    async def execute(self, command: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
        websocket = self._active
        command_id = command["command_id"]
        if not websocket:
            raise ConnectionError("没有已连接的展示执行页面")
        if command_id in self._pending:
            raise ValueError("command_id 重复")
        future = asyncio.get_running_loop().create_future()
        self._pending[command_id] = (command["run_id"], future)
        try:
            await websocket.send_json({"type": "command", **command, "timeout_ms": timeout_ms})
            return await asyncio.wait_for(future, timeout_ms / 1000)
        except BaseException:
            self._pending.pop(command_id, None)
            if not future.done():
                future.cancel()
            raise
