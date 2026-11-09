from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.database import ControlStore
from app.events import EventHub
from app.settings import DATABASE_PATH, PROMO_VIDEO_PATH, WEB_DIR
from app.stream import StreamManager


class StreamStartRequest(BaseModel):
    rtsp_url: str


class MappingsRequest(BaseModel):
    mappings: dict[str, str]


def _local_origin(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        return urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    except ValueError:
        return False


def create_app(database_path: Path = DATABASE_PATH, promo_path: Path = PROMO_VIDEO_PATH) -> FastAPI:
    store = ControlStore(database_path)
    hub = EventHub()
    manager = StreamManager(store, hub)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        hub.bind_loop(asyncio.get_running_loop())
        store.clear_temporary()
        yield
        manager.stop()

    app = FastAPI(title="本地 RTSP 手势控制", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.control_store = store
    app.state.event_hub = hub
    app.state.stream_manager = manager
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.middleware("http")
    async def local_origin_only(request: Request, call_next):
        if not _local_origin(request.headers.get("origin")):
            return StreamingResponse(iter([b"Local access only"]), status_code=403)
        response = await call_next(request)
        if request.url.path in {"/", "/settings"} or request.url.path.startswith(("/static/", "/api/")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/settings")
    async def settings_page() -> FileResponse:
        return FileResponse(WEB_DIR / "settings.html")

    @app.get("/media/promo.mp4")
    async def promo_video() -> FileResponse:
        if not promo_path.is_file():
            raise HTTPException(status_code=404, detail="未找到宣传片，请放入 media/company-promo.mp4")
        return FileResponse(promo_path, media_type="video/mp4")

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

    return app


app = create_app()
