from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.action_engine import ActionRegistry, WorkflowEngine
from app.database import ControlStore
from app.display import DisplayCommandChannel
from app.events import EventHub
from app.ppt_actions import PresentationAdapter, register_ppt_actions
from app.settings import DATABASE_PATH, MEDIA_ASSETS, PRESENTATION_DECKS, PROMO_VIDEO_PATH, WEB_DIR
from app.stream import StreamManager
from app.video_actions import register_video_actions
from app.web_actions import BrowserCommandAdapter, register_web_actions
from app.workflow import new_workflow


class StreamStartRequest(BaseModel):
    rtsp_url: str


class MappingsRequest(BaseModel):
    mappings: dict[str, str]


class RecognitionSettingsRequest(BaseModel):
    gesture_confidence_threshold: float


class WorkflowDryRunRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)


def _local_origin(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        return urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    except ValueError:
        return False


def create_app(database_path: Path = DATABASE_PATH, promo_path: Path = PROMO_VIDEO_PATH) -> FastAPI:
    store = ControlStore(database_path)
    store.sync_media_assets(MEDIA_ASSETS)
    store.sync_presentation_decks(PRESENTATION_DECKS)
    hub = EventHub()
    manager = StreamManager(store, hub)
    display_channel = DisplayCommandChannel()
    browser_adapter = BrowserCommandAdapter(display_channel)
    action_registry = ActionRegistry()
    register_web_actions(action_registry, browser_adapter)
    register_video_actions(action_registry, store, browser_adapter)
    presentation_adapter = PresentationAdapter(store)
    register_ppt_actions(action_registry, store, presentation_adapter)
    workflow_engine = WorkflowEngine(store, action_registry, hub.publish_from_thread)
    display_channel.on_state_change = workflow_engine.set_display_connected
    hub.add_listener(workflow_engine.on_event)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        hub.bind_loop(asyncio.get_running_loop())
        store.clear_temporary()
        yield
        await workflow_engine.close()
        await presentation_adapter.close()
        manager.stop()

    app = FastAPI(title="本地 RTSP 手势控制", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.control_store = store
    app.state.event_hub = hub
    app.state.stream_manager = manager
    app.state.display_channel = display_channel
    app.state.action_registry = action_registry
    app.state.workflow_engine = workflow_engine
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.middleware("http")
    async def local_origin_only(request: Request, call_next):
        if not _local_origin(request.headers.get("origin")):
            return StreamingResponse(iter([b"Local access only"]), status_code=403)
        response = await call_next(request)
        if request.url.path in {"/", "/settings", "/workflows"} or request.url.path.startswith(("/static/", "/api/")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/settings")
    async def settings_page() -> FileResponse:
        return FileResponse(WEB_DIR / "settings.html")

    @app.get("/workflows")
    async def workflows_page() -> FileResponse:
        return FileResponse(WEB_DIR / "workflows.html")

    @app.get("/media/promo.mp4")
    async def promo_video() -> FileResponse:
        if not promo_path.is_file():
            raise HTTPException(status_code=404, detail="未找到宣传片，请放入 media/company-promo.mp4")
        return FileResponse(promo_path, media_type="video/mp4")

    @app.get("/media/assets/{asset_id}")
    async def media_asset(asset_id: str) -> FileResponse:
        asset = store.get_media_asset(asset_id)
        if not asset or not asset["path"].is_file():
            raise HTTPException(status_code=404, detail="未找到已登记的视频素材")
        return FileResponse(asset["path"], media_type="video/mp4")

    @app.get("/api/status")
    async def get_status() -> dict:
        return manager.get_status()

    @app.post("/api/stream/start")
    async def start_stream(payload: StreamStartRequest) -> dict:
        try:
            return manager.start(payload.rtsp_url)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/stream/stop")
    async def stop_stream() -> dict:
        return manager.stop()

    async def mjpeg_generator(request: Request):
        last_frame = None
        while not await request.is_disconnected():
            frame = manager.get_jpeg()
            if frame is not None and frame is not last_frame:
                last_frame = frame
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(frame)}\r\n".encode("ascii")
                    + b"Cache-Control: no-cache, no-store\r\n"
                    + b"\r\n"
                    + frame
                    + b"\r\n"
                )
            await asyncio.sleep(0.04)

    @app.get("/video.mjpg")
    async def video(request: Request) -> StreamingResponse:
        return StreamingResponse(
            mjpeg_generator(request),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/controller/unlock")
    async def unlock_controller() -> dict:
        return {"controller": manager.unlock_controller()}

    @app.get("/api/mappings")
    async def get_mappings() -> dict:
        return {"mappings": store.get_mappings()}

    @app.put("/api/mappings")
    async def put_mappings(payload: MappingsRequest) -> dict:
        try:
            return {"mappings": store.set_mappings(payload.mappings)}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/recognition-settings")
    async def get_recognition_settings() -> dict:
        return manager.get_recognition_settings()

    @app.put("/api/recognition-settings")
    async def put_recognition_settings(payload: RecognitionSettingsRequest) -> dict:
        try:
            return manager.set_gesture_confidence_threshold(payload.gesture_confidence_threshold)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/actions")
    async def get_actions() -> dict:
        return {"actions": action_registry.describe()}

    @app.get("/api/workflow-status")
    async def workflow_status() -> dict:
        return {
            "display_connected": display_channel.connected,
            "active_run_id": workflow_engine.active_run_id,
            "controller": manager.get_status().get("controller", {"state": "unlocked", "track_id": None}),
        }

    @app.post("/api/workflows/validate")
    async def validate_workflow_draft(payload: dict) -> dict:
        errors = workflow_engine.validate(payload)
        return {"valid": not errors, "errors": errors}

    @app.get("/api/workflows")
    async def list_workflows() -> dict:
        return {"workflows": store.get_workflows()}

    @app.post("/api/workflows", status_code=201)
    async def create_workflow(payload: dict) -> dict:
        errors = workflow_engine.validate(payload)
        if errors:
            raise HTTPException(status_code=400, detail=errors)
        try:
            return {"workflow": store.save_workflow(payload)}
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail="工作流结构无效") from error

    @app.get("/api/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str) -> dict:
        workflow = store.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="工作流不存在")
        return {"workflow": workflow}

    @app.put("/api/workflows/{workflow_id}")
    async def update_workflow(workflow_id: str, payload: dict) -> dict:
        current = store.get_workflow(workflow_id)
        if payload.get("id") != workflow_id or not current:
            raise HTTPException(status_code=404, detail="工作流不存在或 ID 不匹配")
        payload["enabled"] = current["enabled"]
        errors = workflow_engine.validate(payload)
        if errors:
            raise HTTPException(status_code=400, detail=errors)
        try:
            return {"workflow": store.save_workflow(payload)}
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail="工作流结构无效") from error

    @app.delete("/api/workflows/{workflow_id}")
    async def delete_workflow(workflow_id: str) -> dict:
        if not store.get_workflow(workflow_id):
            raise HTTPException(status_code=404, detail="工作流不存在")
        workflow_engine.cancel_workflow(workflow_id)
        store.delete_workflow(workflow_id)
        return {"deleted": True}

    @app.post("/api/workflows/{workflow_id}/copy", status_code=201)
    async def copy_workflow(workflow_id: str) -> dict:
        source = store.get_workflow(workflow_id)
        if not source:
            raise HTTPException(status_code=404, detail="工作流不存在")
        copied = new_workflow(source["name"] + " 副本")
        copied.update({key: source[key] for key in ("description", "trigger", "nodes", "edges")})
        copied["enabled"] = False
        errors = workflow_engine.validate(copied)
        if errors:
            raise HTTPException(status_code=400, detail=errors)
        return {"workflow": store.save_workflow(copied)}

    @app.get("/api/workflows/{workflow_id}/versions")
    async def workflow_versions(workflow_id: str) -> dict:
        if not store.get_workflow(workflow_id):
            raise HTTPException(status_code=404, detail="工作流不存在")
        return {"versions": store.get_workflow_versions(workflow_id)}

    @app.post("/api/workflows/{workflow_id}/validate")
    async def validate_workflow(workflow_id: str) -> dict:
        workflow = store.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="工作流不存在")
        errors = workflow_engine.validate(workflow)
        return {"valid": not errors, "errors": errors}

    @app.post("/api/workflows/{workflow_id}/dry-run")
    async def dry_run_workflow(workflow_id: str, payload: WorkflowDryRunRequest | None = None) -> dict:
        workflow = store.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="工作流不存在")
        try:
            run = await workflow_engine.dry_run(workflow, payload.context if payload else {})
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"run": run}

    async def set_workflow_enabled(workflow_id: str, enabled: bool) -> dict:
        workflow = store.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="工作流不存在")
        workflow["enabled"] = enabled
        errors = workflow_engine.validate(workflow)
        if errors:
            raise HTTPException(status_code=400, detail=errors)
        if enabled:
            trigger = workflow["trigger"]
            for other in store.get_workflows(enabled_only=True):
                if other["id"] == workflow_id:
                    continue
                if _triggers_conflict(trigger, other["trigger"]):
                    raise HTTPException(status_code=409, detail=f"触发器与已启用工作流“{other['name']}”冲突")
        return {"workflow": store.save_workflow(workflow)}

    @app.post("/api/workflows/{workflow_id}/enable")
    async def enable_workflow(workflow_id: str) -> dict:
        return await set_workflow_enabled(workflow_id, True)

    @app.post("/api/workflows/{workflow_id}/disable")
    async def disable_workflow(workflow_id: str) -> dict:
        return await set_workflow_enabled(workflow_id, False)

    @app.get("/api/workflow-runs")
    async def list_workflow_runs(limit: int = 50) -> dict:
        return {"runs": store.get_workflow_runs(limit)}

    @app.get("/api/workflow-runs/{run_id}")
    async def get_workflow_run(run_id: str) -> dict:
        run = store.get_workflow_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="工作流运行记录不存在")
        return {"run": run}

    @app.post("/api/workflow-runs/{run_id}/cancel")
    async def cancel_workflow_run(run_id: str) -> dict:
        if not store.get_workflow_run(run_id):
            raise HTTPException(status_code=404, detail="工作流运行记录不存在")
        return {"cancelled": await workflow_engine.cancel_run(run_id)}

    @app.get("/api/media-assets")
    async def media_assets() -> dict:
        return {"media_assets": store.get_media_assets()}

    @app.get("/api/presentations")
    async def presentations() -> dict:
        return {"presentations": store.get_presentations()}

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        if not _local_origin(websocket.headers.get("origin")):
            await websocket.close(code=1008)
            return
        await hub.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await hub.disconnect(websocket)

    @app.websocket("/ws/display")
    async def websocket_display(websocket: WebSocket) -> None:
        if not _local_origin(websocket.headers.get("origin")):
            await websocket.close(code=1008)
            return
        if not await display_channel.connect(websocket):
            return
        try:
            while True:
                raw = await websocket.receive_text()
                if len(raw) > 16384:
                    await websocket.close(code=1009)
                    break
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await display_channel.receive(websocket, message)
        except WebSocketDisconnect:
            pass
        finally:
            await display_channel.disconnect(websocket)

    return app


def _triggers_conflict(left: dict, right: dict) -> bool:
    if left.get("type") == "controller_locked" or right.get("type") == "controller_locked":
        return left.get("type") == right.get("type") == "controller_locked"
    left_gestures = {left["gesture"]} if left.get("type") == "gesture_trigger" else set(left.get("gestures", []))
    right_gestures = {right["gesture"]} if right.get("type") == "gesture_trigger" else set(right.get("gestures", []))
    return bool(left_gestures & right_gestures)


app = create_app()
