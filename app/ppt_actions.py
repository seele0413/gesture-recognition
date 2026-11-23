from __future__ import annotations

import asyncio
import queue
import threading
from pathlib import Path
from typing import Any

from app.action_engine import ActionRegistry
from app.database import ControlStore


class PresentationAdapter:
    """Optional PowerPoint COM adapter. All COM calls run on one STA worker."""

    def __init__(self, store: ControlStore) -> None:
        self.store = store
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._closed = False

    async def execute(self, action: str, params: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("PowerPoint 适配器已关闭")
        deck = self.store.get_presentation(str(params.get("deck_id", "")))
        if not deck:
            raise ValueError("PPT deck_id 未登记")
        path: Path = deck["path"]
        if not path.is_file():
            raise FileNotFoundError(f"PPT 文件不存在：{deck['title']}")
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._ensure_worker()
        self._queue.put((loop, future, action, deck, dict(params)))
        return await future

    def _ensure_worker(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, name="powerpoint-sta", daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            self._drain_unavailable("PowerPoint 控制不可用：请安装 Microsoft PowerPoint 和可选依赖 pywin32")
            return
        app = None
        opened: dict[str, Any] = {}
        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            while True:
                item = self._queue.get()
                if item is None:
                    break
                loop, future, action, deck, params = item
                try:
                    if app is None:
                        try:
                            app = win32com.client.DispatchEx("PowerPoint.Application")
                        except Exception as error:
                            raise RuntimeError("PowerPoint 未安装或 COM 自动化不可用") from error
                        app.Visible = True
                    result = self._perform(app, opened, action, deck, params)
                    loop.call_soon_threadsafe(_set_result, future, result)
                except Exception as error:
                    loop.call_soon_threadsafe(_set_exception, future, RuntimeError(_safe_com_error(error)))
        finally:
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def _drain_unavailable(self, message: str) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            loop, future, _action, _deck, _params = item
            loop.call_soon_threadsafe(_set_exception, future, RuntimeError(message))

    @staticmethod
    def _perform(app: Any, opened: dict[str, Any], action: str, deck: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        deck_id = deck["id"]
        presentation = opened.get(deck_id)
        if action == "ppt.open_deck" or presentation is None:
            if not Path(deck["path"]).is_file():
                raise FileNotFoundError(f"PPT 文件不存在：{deck['title']}")
            presentation = app.Presentations.Open(str(deck["path"]), WithWindow=True)
            opened[deck_id] = presentation
        if action == "ppt.open_deck":
            return {"deck_id": deck_id, "title": deck["title"], "opened": True}
        if action == "ppt.start_slideshow":
            presentation.SlideShowSettings.Run()
        elif action == "ppt.next_slide":
            presentation.SlideShowWindow.View.Next()
        elif action == "ppt.previous_slide":
            presentation.SlideShowWindow.View.Previous()
        elif action == "ppt.goto_slide":
            presentation.SlideShowWindow.View.GotoSlide(int(params["slide_number"]))
        elif action == "ppt.end_slideshow":
            presentation.SlideShowWindow.View.Exit()
        else:
            raise ValueError("未支持的 PowerPoint 操作")
        return {"deck_id": deck_id, "action": action, "success": True}

    async def close(self) -> None:
        self._closed = True
        thread = self._thread
        if not thread or not thread.is_alive():
            return
        self._queue.put(None)
        await asyncio.to_thread(thread.join, 3)


def register_ppt_actions(registry: ActionRegistry, store: ControlStore, adapter: PresentationAdapter) -> None:
    deck_ids = [deck["id"] for deck in store.get_presentations()]
    deck_field = {"type": "string", "title": "登记的演示文稿", "enum": deck_ids}
    deck_actions = (
        "ppt.open_deck", "ppt.start_slideshow", "ppt.next_slide", "ppt.previous_slide", "ppt.end_slideshow",
    )
    for name in deck_actions:
        registry.register(
            name, properties={"deck_id": deck_field}, required=["deck_id"],
            handler=lambda params, context, action=name: adapter.execute(action, params, context),
            idempotent=False,
        )
    registry.register(
        "ppt.goto_slide",
        properties={
            "deck_id": deck_field,
            "slide_number": {"type": "integer", "title": "幻灯片页码", "minimum": 1, "maximum": 10000},
        },
        required=["deck_id", "slide_number"],
        handler=lambda params, context: adapter.execute("ppt.goto_slide", params, context),
        idempotent=True,
    )


def _set_result(future: asyncio.Future, result: dict[str, Any]) -> None:
    if not future.done():
        future.set_result(result)


def _set_exception(future: asyncio.Future, error: Exception) -> None:
    if not future.done():
        future.set_exception(error)


def _safe_com_error(error: Exception) -> str:
    message = str(error)
    if "PowerPoint.Application" in message or "Class not registered" in message:
        return "PowerPoint 未安装或 COM 自动化不可用"
    return message[:300] or "PowerPoint 操作失败"
