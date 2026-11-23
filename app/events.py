from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from fastapi import WebSocket, WebSocketDisconnect


class EventHub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[WebSocket] = set()
        self._listeners: list[Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None] | dict[str, Any] | None]] = []

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add_listener(
        self,
        listener: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None] | dict[str, Any] | None],
    ) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    def publish_from_thread(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(self._schedule_broadcast, event)

    def _schedule_broadcast(self, event: dict[str, Any]) -> None:
        asyncio.create_task(self.broadcast(event))

    async def broadcast(self, event: dict[str, Any]) -> None:
        message = dict(event)
        for listener in tuple(self._listeners):
            try:
                result = listener(message)
                if asyncio.iscoroutine(result):
                    result = await result
                if isinstance(result, dict):
                    message = result
            except Exception:
                continue
        stale = []
        for websocket in tuple(self._clients):
            try:
                await websocket.send_json(message)
            except (RuntimeError, WebSocketDisconnect):
                stale.append(websocket)
        for websocket in stale:
            self._clients.discard(websocket)
