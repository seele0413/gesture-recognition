from __future__ import annotations

import asyncio
from typing import Any
from typing import Callable

from fastapi import WebSocket


class DisplayCommandChannel:
    """A single active browser executor with connection and page-readiness state."""

    def __init__(self) -> None:
        self._active: WebSocket | None = None
        self._lock = asyncio.Lock()
        self._pending: dict[str, tuple[str, asyncio.Future]] = {}
        self._ready_waiters: set[asyncio.Future] = set()
        self._ready_page_id: str | None = None
        self._ready_generation: int | None = None
        self.on_state_change: Callable[[bool], None] | None = None
        self.on_ready_change: Callable[[bool], None] | None = None

    @property
    def connected(self) -> bool:
        return self._active is not None

    @property
    def ready(self) -> bool:
        return self._active is not None and self._ready_page_id is not None

    @property
    def ready_page_id(self) -> str | None:
        return self._ready_page_id if self.ready else None

    @property
    def ready_generation(self) -> int | None:
        return self._ready_generation if self.ready else None

    def _set_ready(self, ready: bool, page_id: str | None = None, generation: int | None = None) -> None:
        previous = self.ready
        if ready:
            self._ready_page_id = page_id
            self._ready_generation = generation
        else:
            self._ready_page_id = None
            self._ready_generation = None

        current = self.ready
        if current and not previous:
            for future in tuple(self._ready_waiters):
                if not future.done():
                    future.set_result(None)
            self._ready_waiters.clear()

        if current != previous and self.on_ready_change:
            self.on_ready_change(current)

    async def connect(self, websocket: WebSocket) -> bool:
        async with self._lock:
            if self._active is not None:
                await websocket.close(code=1013, reason="display client already connected")
                return False
            await websocket.accept()
            self._active = websocket
            self._ready_page_id = None
            self._ready_generation = None
        if self.on_state_change:
            self.on_state_change(True)
        return True

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if self._active is not websocket:
                return
            self._active = None
            self._set_ready(False)
            pending = [future for _run_id, future in self._pending.values()]
            self._pending.clear()
            ready_waiters = tuple(self._ready_waiters)
            self._ready_waiters.clear()

        for future in pending:
            if not future.done():
                future.set_exception(ConnectionError("展示执行客户端已断开"))
        for future in ready_waiters:
            if not future.done():
                future.set_exception(ConnectionError("展示页面尚未就绪，执行客户端已断开"))
        if self.on_state_change:
            self.on_state_change(False)

    async def receive(self, websocket: WebSocket, message: Any) -> None:
        if websocket is not self._active or not isinstance(message, dict):
            return

        message_type = message.get("type")
        if message_type == "display:loading":
            self._set_ready(False)
            return

        if message_type == "display:ready":
            page_id = message.get("page_id")
            generation = message.get("generation")
            if (
                not isinstance(page_id, str)
                or not page_id
                or isinstance(generation, bool)
                or not isinstance(generation, int)
                or generation < 0
            ):
                return
            self._set_ready(True, page_id, generation)
            return

        if message_type != "ack":
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

    async def _wait_until_ready(self, timeout_ms: int) -> None:
        if self.ready:
            return
        future = asyncio.get_running_loop().create_future()
        self._ready_waiters.add(future)
        try:
            await asyncio.wait_for(future, max(100, min(30000, timeout_ms)) / 1000)
        except asyncio.TimeoutError as error:
            raise TimeoutError("展示页面尚未完成加载") from error
        finally:
            self._ready_waiters.discard(future)

    async def execute(self, command: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
        await self._wait_until_ready(timeout_ms)
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
