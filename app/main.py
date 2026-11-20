from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, root_validator

from app.action_engine import ActionRegistry, WorkflowEngine
from app.database import ControlStore
from app.display import DisplayCommandChannel
from app.display_pages import normalize_external_url, validate_display_page_id
from app.events import EventHub
from app.ppt_actions import PresentationAdapter, register_ppt_actions
from app.settings import DATABASE_PATH, MEDIA_ASSETS, PRESENTATION_DECKS, PROMO_VIDEO_PATH, WEB_DIR
from app.stream import StreamManager
from app.video_actions import register_video_actions
from app.web_actions import BrowserCommandAdapter, register_web_actions
from app.workflow import new_workflow
from app.workflow_generator import (
    MAX_UPLOAD_BYTES,
    DocumentParseError,
    ModelNotConfiguredError,
    ModelRequestError,
    WorkflowGenerationError,
    WorkflowGenerator,
    build_generated_workflow,
    external_page_control_issues,
    extract_document_text,
)


class StreamStartRequest(BaseModel):
    rtsp_url: str


class MappingsRequest(BaseModel):
    mappings: dict[str, str]


class RecognitionSettingsRequest(BaseModel):
    gesture_confidence_threshold: float


class WorkflowGeneratorConfigRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)

    class Config:
        extra = "forbid"

    @root_validator(pre=True)
    def validate_api_key_value(cls, values):
        if not isinstance(values, dict):
            return values
        value = values.get("api_key")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("请输入有效的 OpenAI API Key")
        if any(character.isspace() for character in value.strip()) or "\x00" in value:
            raise ValueError("API Key 格式无效，请检查是否包含空格或换行")
        return {"api_key": value.strip()}


class DisplayPageCreateRequest(BaseModel):
    page_id: str
    title: str
    url: str
    description: str = ""
    parent_id: str | None = None
    enabled: bool = True

    class Config:
        extra = "forbid"


class DisplayPageUpdateRequest(BaseModel):
    title: str | None = None
    url: str | None = None
    description: str | None = None
    parent_id: str | None = None
    enabled: bool | None = None

    class Config:
        extra = "forbid"


class DisplayUrlRequest(BaseModel):
    url: str

    class Config:
        extra = "forbid"


class DefaultDisplayPageRequest(BaseModel):
    page_id: str

    class Config:
        extra = "forbid"


class WorkflowDryRunRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)


class PointerModeRequest(BaseModel):
    enabled: bool


class PointerSettingsRequest(BaseModel):
    min_cutoff: float | None = None
    beta: float | None = None
    derivative_cutoff: float | None = None
    press_threshold: float | None = None
    release_threshold: float | None = None
    press_stable_frames: int | None = None
    release_stable_frames: int | None = None
    max_update_hz: float | None = None
    dropout_grace_ms: int | None = None

    class Config:
        extra = "forbid"

    @root_validator(pre=True)
    def reject_invalid_pointer_setting_types(cls, values):
        if not isinstance(values, dict):
            return values
        integer_fields = {"press_stable_frames", "release_stable_frames", "dropout_grace_ms"}
        numeric_fields = {
            "min_cutoff", "beta", "derivative_cutoff", "press_threshold",
            "release_threshold", "max_update_hz",
        }
        for name, value in values.items():
            if name in integer_fields and (isinstance(value, bool) or not isinstance(value, int)):
                raise ValueError(f"{name} 必须使用整数")
            if name in numeric_fields and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise ValueError(f"{name} 必须使用数值")
        return values


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
    register_web_actions(action_registry, browser_adapter, store.get_display_page_ids, store.get_display_page_labels)
    register_video_actions(action_registry, store, browser_adapter)
    presentation_adapter = PresentationAdapter(store)
    register_ppt_actions(action_registry, store, presentation_adapter)
    workflow_engine = WorkflowEngine(store, action_registry, hub.publish_from_thread)
    workflow_generator = WorkflowGenerator()
    display_channel.on_state_change = workflow_engine.set_display_connected
    display_channel.on_ready_change = workflow_engine.set_display_ready
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
    app.state.workflow_generator = workflow_generator

    def validate_workflow_definition(definition: dict) -> list[str]:
        errors = workflow_engine.validate(definition)
        errors.extend(
            external_page_control_issues(
                definition,
                store.get_display_pages(),
                store.get_default_display_page_id(),
            )
        )
        return errors
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.middleware("http")
    async def local_origin_only(request: Request, call_next):
        if not _local_origin(request.headers.get("origin")):
            return StreamingResponse(iter([b"Local access only"]), status_code=403)
        response = await call_next(request)
        if request.url.path in {"/", "/settings", "/workflows", "/display-pages"} or request.url.path.startswith(("/static/", "/api/")):
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

    @app.get("/display-pages")
    async def display_pages_page() -> FileResponse:
        return FileResponse(WEB_DIR / "display-pages.html")

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

    def validate_external_page_values(values: dict[str, Any], current_page_id: str | None = None) -> dict[str, Any]:
        page_id = validate_display_page_id(current_page_id or values.get("page_id"))
        title = values.get("title")
        description = values.get("description", "")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise ValueError("页面名称长度必须为 1～120 个字符")
        if not isinstance(description, str) or len(description) > 500:
            raise ValueError("页面说明不能超过 500 个字符")
        normalized_url = normalize_external_url(values.get("url"))
        parent_id = values.get("parent_id")
        if parent_id is not None:
            parent_id = validate_display_page_id(parent_id)
            if parent_id == page_id:
                raise ValueError("页面不能将自己设置为父页面")
            parent = store.get_display_page(parent_id)
            if not parent or parent["page_type"] != "external":
                raise ValueError("父页面必须是已登记的外部网页")
            if not parent["enabled"]:
                current_page = store.get_display_page(current_page_id) if current_page_id else None
                current_enabled = bool(
                    values.get("enabled", current_page["enabled"] if current_page else True)
                )
                can_preserve_disabled_parent = (
                    current_page is not None
                    and not current_page["enabled"]
                    and not current_enabled
                    and current_page["parent_id"] == parent_id
                )
                if not can_preserve_disabled_parent:
                    raise ValueError("新建或启用子页面时，父页面必须处于启用状态")
            ancestor = parent
            visited: set[str] = set()
            while ancestor:
                ancestor_id = ancestor["page_id"]
                if ancestor_id == page_id or ancestor_id in visited:
                    raise ValueError("页面父子关系不能形成循环")
                visited.add(ancestor_id)
                ancestor = store.get_display_page(ancestor["parent_id"]) if ancestor["parent_id"] else None
            if urlsplit(parent["url"]).hostname != urlsplit(normalized_url).hostname:
                raise ValueError("子页面必须与父页面属于同一个域名")
        return {
            "page_id": page_id,
            "title": title.strip(),
            "description": description.strip(),
            "url": normalized_url,
            "parent_id": parent_id,
            "page_type": "external",
            "enabled": bool(values.get("enabled", True)),
        }

    @app.get("/api/display/pages")
    async def get_display_pages(include_disabled: bool = False) -> dict:
        return {
            "default_page_id": store.get_default_display_page_id(),
            "pages": store.get_display_pages(include_disabled=include_disabled),
        }

    @app.post("/api/display/pages/validate-url")
    async def validate_display_url(payload: DisplayUrlRequest) -> dict:
        try:
            normalized = normalize_external_url(payload.url)
            return {"valid": True, "url": normalized, "hostname": urlsplit(normalized).hostname}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/display/pages", status_code=201)
    async def create_display_page(payload: DisplayPageCreateRequest) -> dict:
        try:
            clean = validate_external_page_values(payload.dict())
            return {"page": store.create_display_page(clean)}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="页面 ID 已存在或父页面关系无效") from error

    @app.put("/api/display/pages/{page_id}")
    async def update_display_page(page_id: str, payload: DisplayPageUpdateRequest) -> dict:
        current = store.get_display_page(page_id)
        if not current:
            raise HTTPException(status_code=404, detail="展示页面不存在")
        if current["page_type"] != "external":
            raise HTTPException(status_code=400, detail="内置本地展示页面不能通过网页管理接口修改")
        values = {
            "title": current["title"],
            "description": current["description"],
            "url": current["url"],
            "parent_id": current["parent_id"],
            "enabled": current["enabled"],
        }
        values.update(payload.dict(exclude_unset=True))
        try:
            clean = validate_external_page_values(values, current_page_id=page_id)
            return {"page": store.update_display_page(page_id, clean)}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.delete("/api/display/pages/{page_id}")
    async def delete_display_page(page_id: str) -> dict:
        try:
            deleted = store.delete_display_page(page_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not deleted:
            raise HTTPException(status_code=404, detail="展示页面不存在")
        return {"deleted": True}

    @app.post("/api/display/default")
    async def set_default_display_page(payload: DefaultDisplayPageRequest) -> dict:
        try:
            return {"default_page_id": store.set_default_display_page_id(payload.page_id)}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

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

    @app.get("/api/workflow-generator/status")
    async def workflow_generator_status() -> dict:
        return workflow_generator.status()

    @app.put("/api/workflow-generator/config")
    async def update_workflow_generator_config(payload: WorkflowGeneratorConfigRequest) -> dict:
        try:
            # The secret is written to the ignored local .env file and is never returned.
            return workflow_generator.configure_api_key(payload.api_key)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/workflows/generate")
    async def generate_workflow_from_document(
        file: UploadFile = File(...),
        instructions: str = Form(""),
        preferred_trigger: str = Form("Open_Palm"),
    ) -> dict:
        try:
            document_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
            extracted = extract_document_text(file.filename, document_bytes)
            action_schemas = action_registry.schema_map()
            pages = store.get_display_pages()
            plan = await asyncio.to_thread(
                workflow_generator.generate_plan,
                extracted["text"],
                instructions,
                preferred_trigger,
                action_schemas,
                pages,
            )
            generated, warnings, questions, summary = build_generated_workflow(plan, action_schemas)
            validation_errors = validate_workflow_definition(generated)
            return {
                "workflow": generated,
                "valid": not validation_errors,
                "validation_errors": validation_errors,
                "warnings": warnings,
                "questions": questions,
                "summary": summary,
                "source": {
                    "filename": extracted["filename"],
                    "character_count": extracted["character_count"],
                },
            }
        except DocumentParseError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ModelNotConfiguredError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ModelRequestError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except WorkflowGenerationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            await file.close()

    @app.get("/api/pointer/settings")
    async def get_pointer_settings() -> dict:
        return manager.get_pointer_settings()

    @app.put("/api/pointer/settings")
    async def put_pointer_settings(payload: PointerSettingsRequest) -> dict:
        try:
            return manager.set_pointer_settings(payload.dict(exclude_unset=True, exclude_none=True))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/pointer/mode")
    async def get_pointer_mode() -> dict:
        status = manager.get_status()
        return {
            "enabled": status.get("pointer_mode_enabled", False),
            "controller": status.get("controller", {"state": "unlocked", "track_id": None}),
        }

    @app.post("/api/pointer/mode")
    async def set_pointer_mode(payload: PointerModeRequest) -> dict:
        return manager.set_pointer_mode(payload.enabled)

    @app.get("/api/workflow-status")
    async def workflow_status() -> dict:
        return {
            "display_connected": display_channel.connected,
            "display_ready": display_channel.ready,
            "display_page_id": display_channel.ready_page_id,
            "display_generation": display_channel.ready_generation,
            "active_run_id": workflow_engine.active_run_id,
            "controller": manager.get_status().get("controller", {"state": "unlocked", "track_id": None}),
        }

    @app.post("/api/workflows/validate")
    async def validate_workflow_draft(payload: dict) -> dict:
        errors = validate_workflow_definition(payload)
        return {"valid": not errors, "errors": errors}

    @app.get("/api/workflows")
    async def list_workflows() -> dict:
        return {"workflows": store.get_workflows()}

    @app.post("/api/workflows", status_code=201)
    async def create_workflow(payload: dict) -> dict:
        errors = validate_workflow_definition(payload)
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
        errors = validate_workflow_definition(payload)
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
        errors = validate_workflow_definition(copied)
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
        errors = validate_workflow_definition(workflow)
        return {"valid": not errors, "errors": errors}

    @app.post("/api/workflows/{workflow_id}/dry-run")
    async def dry_run_workflow(workflow_id: str, payload: WorkflowDryRunRequest | None = None) -> dict:
        workflow = store.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="工作流不存在")
        errors = validate_workflow_definition(workflow)
        if errors:
            raise HTTPException(status_code=400, detail=errors)
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
        errors = validate_workflow_definition(workflow)
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
