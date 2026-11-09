from __future__ import annotations

import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from app.control import build_controller_event, validate_rtsp_url
from app.decoder import PyAVDecoder
from app.database import ControlStore
from app.events import EventHub
from app.settings import MODEL_DIR


FRAME_STALE_MS = 5000
RECONNECT_DELAYS_SECONDS = (1, 2, 4, 8, 10)
MAX_CONSECUTIVE_PROCESSING_ERRORS = 3


class _VisionProcessingFailure(RuntimeError):
    """Raised when repeated frame-processing failures require a fresh session."""



def _empty_vision() -> dict[str, Any]:
    return {
        "hand_count": 0,
        "ok_hand_count": 0,
        "associated_hand_count": 0,
        "associated_ok_count": 0,
        "hands": [],
        "lock_progress": 0,
        "last_gesture": None,
    }


class _LatestFrameReader:
    """Read frames continuously while keeping only the newest unprocessed frame."""

    def __init__(self, decoder: Any, stop_event: threading.Event, on_drop: Any = None):
        self._decoder = decoder
        self._stream_stop_event = stop_event
        self._stop_event = threading.Event()
        self._on_drop = on_drop
        self._frames: queue.Queue = queue.Queue(maxsize=1)
        self._finished = threading.Event()
        self._failed = False
        self._drop_lock = threading.Lock()
        self._dropped_frames = 0
        self._thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name="rtsp-decoder",
        )

    def start(self) -> None:
        self._thread.start()

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    @property
    def dropped_frames(self) -> int:
        with self._drop_lock:
            return self._dropped_frames

    def wait_finished(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)

    def _record_drop(self) -> None:
        with self._drop_lock:
            self._dropped_frames += 1
        if self._on_drop:
            try:
                self._on_drop()
            except Exception:
                pass

    def _publish_latest(self, frame: Any) -> None:
        item = (frame, time.monotonic())
        try:
            self._frames.put_nowait(item)
            return
        except queue.Full:
            pass

        try:
            self._frames.get_nowait()
        except queue.Empty:
            pass
        else:
            self._record_drop()

        try:
            self._frames.put_nowait(item)
        except queue.Full:
            # The consumer won the race and another producer is not expected.
            pass

    def _read_loop(self) -> None:
        try:
            while not self._stop_event.is_set() and not self._stream_stop_event.is_set():
                try:
                    ok, frame = self._decoder.read()
                except Exception:
                    self._failed = True
                    break
                if not ok or frame is None:
                    self._failed = True
                    break
                self._publish_latest(frame)
        finally:
            self._finished.set()

    def read(self, timeout: float = 0.5) -> tuple[Any, float] | None:
        if self._stop_event.is_set() or self._stream_stop_event.is_set():
            return None
        try:
            return self._frames.get(timeout=timeout)
        except queue.Empty:
            if self._finished.is_set() and self._frames.empty():
                if self._failed and not self._stream_stop_event.is_set():
                    raise RuntimeError("decoder_read_failed") from None
            return None

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)


class StreamManager:
    def __init__(
        self,
        store: ControlStore,
        hub: EventHub,
        models_dir: Path = MODEL_DIR,
        capture_factory: Any = None,
        processor_factory: Any = None,
        decoder_factory: Any = None,
        reconnect_delays: tuple[float, ...] = RECONNECT_DELAYS_SECONDS,
    ):
        self.store = store
        self.hub = hub
        self.models_dir = models_dir
        self.capture_factory = capture_factory
        self.processor_factory = processor_factory
        self.decoder_factory = decoder_factory
        self.reconnect_delays = reconnect_delays
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._decoder: Any = None
        self._processor: Any = None
        self._state = "stopped"
        self._error: str | None = None
        self._latest_jpeg: bytes | None = None
        self._frame_width = 0
        self._frame_height = 0
        self._vision = _empty_vision()
        self._tracks: list[dict[str, Any]] = []
        self._controller: dict[str, Any] = {"state": "unlocked", "track_id": None, "lost_since_ms": None}
        self._session_id: str | None = None
        self._frame_sequence = 0
        self._last_frame_at_ms: int | None = None
        self._decoder_name: str | None = None
        self._reconnect_attempt = 0
        self._reconnect_count = 0
        self._dropped_frames = 0
        self._last_processing_ms: float | None = None
        self._last_queue_delay_ms: float | None = None

    def start(self, rtsp_url: str) -> dict[str, Any]:
        rtsp_url = validate_rtsp_url(rtsp_url)
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise ValueError("当前视频流仍在运行，请先停止后再切换地址")
            self.store.clear_temporary()
            self._session_id = None
            self._stop_event = threading.Event()
            self._state = "connecting"
            self._error = None
            self._latest_jpeg = None
            self._tracks = []
            self._controller = {"state": "unlocked", "track_id": None, "lost_since_ms": None}
            self._frame_width = 0
            self._frame_height = 0
            self._vision = _empty_vision()
            self._frame_sequence = 0
            self._last_frame_at_ms = None
            self._decoder_name = None
            self._reconnect_attempt = 0
            self._reconnect_count = 0
            self._dropped_frames = 0
            self._last_processing_ms = None
            self._last_queue_delay_ms = None
            self._thread = threading.Thread(
                target=self._run,
                args=(rtsp_url, self._stop_event),
                daemon=True,
                name="rtsp-vision",
            )
            self._thread.start()
            return self.get_status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            thread = self._thread
            decoder = self._decoder
            session_id = self._session_id
            was_locked = self._controller["state"] != "unlocked"
            self._stop_event.set()
        if decoder is not None:
            try:
                decoder.close()
            except Exception:
                pass
        if thread and thread is not threading.current_thread():
            thread.join(timeout=6)
        if session_id:
            self.store.clear_temporary(session_id)
        with self._lock:
            self._state = "stopped"
            self._error = None
            self._latest_jpeg = None
            self._tracks = []
            self._frame_width = 0
            self._frame_height = 0
            self._vision = _empty_vision()
            self._processor = None
            self._decoder = None
            self._session_id = None
            self._decoder_name = None
            self._last_frame_at_ms = None
            self._reconnect_attempt = 0
            self._reconnect_count = 0
            self._dropped_frames = 0
            self._last_processing_ms = None
            self._last_queue_delay_ms = None
            self._controller = {"state": "unlocked", "track_id": None, "lost_since_ms": None}
            status = self.get_status()
        if was_locked:
            self.hub.publish_from_thread(
                build_controller_event(
                    state="unlocked",
                    track_id=None,
                    timestamp_ms=int(time.time() * 1000),
                    reason="stream_stopped",
                )
            )
        return status

    def unlock_controller(self) -> dict[str, Any]:
        with self._lock:
            processor = self._processor
            if processor and self._state == "running":
                self._controller = processor.unlock_controller()
            else:
                was_locked = self._controller["state"] != "unlocked"
                self._controller = {"state": "unlocked", "track_id": None, "lost_since_ms": None}
                if was_locked:
                    self.hub.publish_from_thread(
                        build_controller_event(
                            state="unlocked",
                            track_id=None,
                            timestamp_ms=int(time.time() * 1000),
                            reason="manual",
                        )
                    )
            return dict(self._controller)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            processor = self._processor
            controller = processor.controller.snapshot() if processor else dict(self._controller)
            now_ms = int(time.time() * 1000)
            frame_age_ms = (
                max(0, now_ms - self._last_frame_at_ms)
                if self._last_frame_at_ms is not None
                else None
            )
            frame_fresh = (
                self._state == "running"
                and self._latest_jpeg is not None
                and frame_age_ms is not None
                and frame_age_ms <= FRAME_STALE_MS
            )
            return {
                "state": self._state,
                "error": self._error,
                "frame_width": self._frame_width,
                "frame_height": self._frame_height,
                "frame_ready": frame_fresh,
                "frame_fresh": frame_fresh,
                "frame_sequence": self._frame_sequence,
                "last_frame_at_ms": self._last_frame_at_ms,
                "frame_age_ms": frame_age_ms,
                "decoder": self._decoder_name,
                "reconnect_attempt": self._reconnect_attempt,
                "reconnect_count": self._reconnect_count,
                "dropped_frames": self._dropped_frames,
                "last_processing_ms": self._last_processing_ms,
                "last_queue_delay_ms": self._last_queue_delay_ms,
                "tracks": [track.copy() for track in self._tracks],
                "controller": controller,
                "vision": dict(self._vision),
            }

    def get_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def _open_decoder(self, rtsp_url: str) -> Any:
        if self.decoder_factory:
            return self.decoder_factory(rtsp_url)
        if self.capture_factory:
            return self.capture_factory(rtsp_url)
        return PyAVDecoder(rtsp_url)

    def _create_processor(self, session_id: str) -> Any:
        if self.processor_factory:
            return self.processor_factory(
                self.store, self.hub.publish_from_thread, self.models_dir, session_id
            )
        from app.vision import ModelsMissingError, VisionProcessor

        return VisionProcessor(
            self.store,
            self.hub.publish_from_thread,
            self.models_dir,
            session_id,
        )

    @staticmethod
    def _close_decoder(decoder: Any) -> None:
        if decoder is None:
            return
        close = getattr(decoder, "close", None) or getattr(decoder, "release", None)
        if close:
            close()

    def _record_dropped_frame(self) -> None:
        with self._lock:
            self._dropped_frames += 1

    def _run(self, rtsp_url: str, stop_event: threading.Event) -> None:
        import cv2

        reconnect_attempt = 0
        try:
            while not stop_event.is_set():
                decoder = None
                processor = None
                reader = None
                session_id: str | None = None
                retry_delay: int | None = None
                fatal = False
                try:
                    decoder = self._open_decoder(rtsp_url)
                    is_opened = getattr(decoder, "isOpened", None)
                    if is_opened and not is_opened():
                        raise RuntimeError("decoder_open_failed")
                    if stop_event.is_set():
                        break

                    session_id = uuid.uuid4().hex
                    self.store.clear_temporary()
                    self.store.begin_session(session_id, int(time.time() * 1000))
                    with self._lock:
                        self._session_id = session_id
                        self._decoder = decoder
                        self._decoder_name = getattr(
                            decoder,
                            "name",
                            "替身解码器" if self.decoder_factory or self.capture_factory else "PyAV / FFmpeg",
                        )

                    try:
                        processor = self._create_processor(session_id)
                    except Exception as error:
                        from app.vision import ModelsMissingError

                        if isinstance(error, ModelsMissingError):
                            self._set_error(str(error))
                        else:
                            self._set_error(f"视觉模型启动失败（{type(error).__name__}）。请检查依赖和模型安装。")
                        fatal = True
                        break

                    was_reconnecting = reconnect_attempt > 0
                    with self._lock:
                        if stop_event.is_set():
                            break
                        self._processor = processor
                        self._state = "running"
                        self._error = None
                    if was_reconnecting:
                        self.hub.publish_from_thread(
                            {"type": "stream", "state": "running", "message": "摄像头已恢复，请重新做 OK 手势锁定主控。"}
                        )

                    reader = _LatestFrameReader(
                        decoder, stop_event, self._record_dropped_frame
                    )
                    reader.start()

                    processing_errors = 0
                    while not stop_event.is_set():
                        item = reader.read(timeout=0.5)
                        if item is None:
                            if stop_event.is_set():
                                break
                            continue
                        frame, received_at = item
                        processing_started = time.monotonic()
                        queue_delay_ms = max(0.0, (processing_started - received_at) * 1000)

                        try:
                            result = processor.process(frame)
                        except Exception:
                            processing_errors += 1
                            if processing_errors >= MAX_CONSECUTIVE_PROCESSING_ERRORS:
                                raise _VisionProcessingFailure from None
                            continue
                        processing_errors = 0

                        encoded, jpeg = cv2.imencode(
                            ".jpg", result["frame"], [cv2.IMWRITE_JPEG_QUALITY, 82]
                        )
                        if not encoded:
                            continue
                        processing_ms = (time.monotonic() - processing_started) * 1000
                        now_ms = int(time.time() * 1000)
                        with self._lock:
                            self._latest_jpeg = jpeg.tobytes()
                            self._frame_width = result["frame_width"]
                            self._frame_height = result["frame_height"]
                            self._frame_sequence += 1
                            self._last_frame_at_ms = now_ms
                            self._tracks = result["tracks"]
                            self._controller = result["controller"]
                            self._vision = result.get("vision", self._vision)
                            self._last_processing_ms = round(processing_ms, 1)
                            self._last_queue_delay_ms = round(queue_delay_ms, 1)
                            self._reconnect_attempt = 0
                        reconnect_attempt = 0

                    if fatal or stop_event.is_set():
                        break
                except Exception as error:
                    if stop_event.is_set():
                        break
                    reconnect_attempt += 1
                    retry_delay = self.reconnect_delays[
                        min(reconnect_attempt - 1, len(self.reconnect_delays) - 1)
                    ]
                    reconnect_message = (
                        "连续多帧视觉处理失败，正在重新初始化解码器和识别模型。"
                        if isinstance(error, _VisionProcessingFailure)
                        else "视频流中断，正在自动重连。请检查摄像头和网络；恢复后需要重新做 OK 手势锁定。"
                    )
                    self._enter_reconnecting(
                        session_id, reconnect_attempt, retry_delay, reconnect_message
                    )
                    session_id = None
                finally:
                    if reader is not None:
                        reader.stop()
                    try:
                        self._close_decoder(decoder)
                    except Exception:
                        pass
                    if reader is not None:
                        reader.join(timeout=6)
                    if processor is not None:
                        try:
                            processor.close()
                        except Exception:
                            pass
                    if session_id:
                        self.store.clear_temporary(session_id)
                    with self._lock:
                        if self._processor is processor:
                            self._processor = None
                        if self._decoder is decoder:
                            self._decoder = None
                        if session_id and self._session_id == session_id:
                            self._session_id = None

                if fatal or stop_event.is_set():
                    break
                if retry_delay is None:
                    break
                if stop_event.wait(retry_delay):
                    break
        finally:
            with self._lock:
                session_id = self._session_id
                self._session_id = None
                self._decoder = None
                self._processor = None
                self._tracks = []
                self._vision = _empty_vision()
                self._controller = {"state": "unlocked", "track_id": None, "lost_since_ms": None}
                self._latest_jpeg = None
                self._last_frame_at_ms = None
                self._decoder_name = None
                if stop_event.is_set():
                    self._state = "stopped"
            if session_id:
                self.store.clear_temporary(session_id)

    def _enter_reconnecting(
        self, session_id: str | None, attempt: int, retry_delay: int, message: str | None = None
    ) -> None:
        with self._lock:
            processor = self._processor
            controller = processor.controller.snapshot() if processor else dict(self._controller)
            was_locked = controller["state"] != "unlocked"
            self._state = "reconnecting"
            self._error = message or "视频流中断，正在自动重连。请检查摄像头和网络；恢复后需要重新做 OK 手势。"
            self._latest_jpeg = None
            self._frame_width = 0
            self._frame_height = 0
            self._last_frame_at_ms = None
            self._tracks = []
            self._vision = _empty_vision()
            self._controller = {"state": "unlocked", "track_id": None, "lost_since_ms": None}
            self._processor = None
            self._decoder = None
            self._session_id = None
            self._decoder_name = None
            self._reconnect_attempt = attempt
            self._reconnect_count += 1
        if session_id:
            self.store.clear_temporary(session_id)
        if was_locked:
            self.hub.publish_from_thread(
                build_controller_event(
                    state="unlocked",
                    track_id=None,
                    timestamp_ms=int(time.time() * 1000),
                    reason="stream_reconnected",
                )
            )
        self.hub.publish_from_thread(
            {
                "type": "stream",
                "state": "reconnecting",
                "attempt": attempt,
                "retry_in_seconds": retry_delay,
                "message": self._error,
            }
        )

    def _set_error(self, message: str) -> None:
        with self._lock:
            if self._stop_event.is_set():
                self._state = "stopped"
                return
            self._state = "error"
            self._error = message
        self.hub.publish_from_thread({"type": "stream", "state": "error", "message": message})
