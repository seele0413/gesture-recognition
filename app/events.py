from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class EventHub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[WebSocket] = set()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

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
        stale = []
        for websocket in tuple(self._clients):
            try:
                await websocket.send_json(event)
            except (RuntimeError, WebSocketDisconnect):
                stale.append(websocket)
        for websocket in stale:
            self._clients.discard(websocket)
