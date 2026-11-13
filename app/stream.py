from __future__ import annotations

import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.control import DEFAULT_GESTURE_CONFIDENCE_THRESHOLD, build_controller_event, validate_rtsp_url
from app.decoder import PyAVDecoder
from app.database import ControlStore
from app.events import EventHub
from app.settings import MAX_INFERENCE_WIDTH, MODEL_DIR


FRAME_STALE_MS = 5000
RECONNECT_DELAYS_SECONDS = (1, 2, 4, 8, 10)
MAX_CONSECUTIVE_PROCESSING_ERRORS = 3
PREVIEW_MAX_WIDTH = MAX_INFERENCE_WIDTH
PREVIEW_MAX_FPS = 30.0
FPS_WINDOW_SECONDS = 5.0


@dataclass(frozen=True)
class _FramePacket:
    frame: Any
    decoded_at: float
    enqueued_at: float
    source_sequence: int
    frame_resize_ms: float = 0.0

    def __iter__(self):
        yield self.frame
        yield self.enqueued_at


class _VisionProcessingFailure(RuntimeError):
    """Raised when repeated frame-processing failures require a fresh session."""



def _empty_controller() -> dict[str, Any]:
    return {
        "state": "unlocked",
        "controller_id": None,
        "track_id": None,
        "lost_since_ms": None,
        "recovery_deadline_ms": None,
        "suspect_grace_ms": 800,
        "reacquire_timeout_ms": 4000,
        "reacquisition_count": 0,
        "last_reacquisition_method": None,
        "last_reason": "not_locked",
        "lock_progress": 0,
        "lock_required_frames": 2,
        "lock_window_frames": 5,
    }


def _empty_vision() -> dict[str, Any]:
    return {
        "hand_count": 0,
        "ok_hand_count": 0,
        "associated_hand_count": 0,
        "associated_ok_count": 0,
        "hands": [],
        "lock_progress": 0,
        "last_gesture": None,
        "confidence_threshold": DEFAULT_GESTURE_CONFIDENCE_THRESHOLD,
        "low_confidence_hand_count": 0,
        "low_confidence_result_count": 0,
        "timings": {},
    }


class _LatestFrameReader:
    """Read frames continuously while keeping only the newest unprocessed frame."""

    def __init__(
        self,
        decoder: Any,
        stop_event: threading.Event,
        on_drop: Any = None,
        on_frame: Any = None,
    ):
        self._decoder = decoder
        self._stream_stop_event = stop_event
        self._stop_event = threading.Event()
        self._on_drop = on_drop
        self._on_frame = on_frame
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

    def _publish_latest(self, item: _FramePacket) -> None:
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
                decoded_at = time.monotonic()
                source_sequence = 0
                frame_resize_ms = 0.0
                if self._on_frame:
                    try:
                        frame, source_sequence, frame_resize_ms = self._on_frame(frame, decoded_at)
                    except Exception:
                        self._failed = True
                        break
                self._publish_latest(
                    _FramePacket(
                        frame=frame,
                        decoded_at=decoded_at,
                        enqueued_at=time.monotonic(),
                        source_sequence=source_sequence,
                        frame_resize_ms=frame_resize_ms,
                    )
                )
        finally:
            self._finished.set()

    def read(self, timeout: float = 0.5) -> _FramePacket | None:
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
        self._confidence_threshold = store.get_gesture_confidence_threshold()
        self._pointer_mode_enabled = False
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
        self._controller: dict[str, Any] = _empty_controller()
        self._session_id: str | None = None
        self._frame_sequence = 0
        self._last_frame_at_ms: int | None = None
        self._last_preview_frame_at_ms: int | None = None
        self._decoder_name: str | None = None
        self._reconnect_attempt = 0
        self._reconnect_count = 0
        self._dropped_frames = 0
        self._last_vision_ms: float | None = None
        self._last_jpeg_encode_ms: float | None = None
        self._last_queue_delay_ms: float | None = None
        self._last_frame_age_to_ai_ms: float | None = None
        self._last_vision_at_ms: int | None = None
        self._decoded_frame_sequence = 0
        self._preview_frame_sequence = 0
        self._vision_frame_sequence = 0
        self._preview_times: deque[float] = deque(maxlen=180)
        self._ai_times: deque[float] = deque(maxlen=180)
        self._preview_fps = 0.0
        self._ai_fps = 0.0
        self._last_preview_encode_at: float | None = None

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
            self._controller = _empty_controller()
            self._frame_width = 0
            self._frame_height = 0
            self._vision = _empty_vision()
            self._frame_sequence = 0
            self._last_frame_at_ms = None
            self._last_preview_frame_at_ms = None
            self._decoder_name = None
            self._reconnect_attempt = 0
            self._reconnect_count = 0
            self._dropped_frames = 0
            self._last_vision_ms = None
            self._last_jpeg_encode_ms = None
            self._last_queue_delay_ms = None
            self._last_frame_age_to_ai_ms = None
            self._last_vision_at_ms = None
            self._decoded_frame_sequence = 0
            self._preview_frame_sequence = 0
            self._vision_frame_sequence = 0
            self._preview_times.clear()
            self._ai_times.clear()
            self._preview_fps = 0.0
            self._ai_fps = 0.0
            self._last_preview_encode_at = None
            self._thread = threading.Thread(
                target=self._run,
                args=(rtsp_url, self._stop_event),
                daemon=True,
                name="rtsp-vision",
            )
            self._thread.start()
            return self.get_status()

    def stop(self) -> dict[str, Any]:
        self.set_pointer_mode(False)
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
            self._last_preview_frame_at_ms = None
            self._reconnect_attempt = 0
            self._reconnect_count = 0
            self._dropped_frames = 0
            self._last_vision_ms = None
            self._last_jpeg_encode_ms = None
            self._last_queue_delay_ms = None
            self._last_frame_age_to_ai_ms = None
            self._last_vision_at_ms = None
            self._preview_times.clear()
            self._ai_times.clear()
            self._preview_fps = 0.0
            self._ai_fps = 0.0
            self._last_preview_encode_at = None
            self._controller = _empty_controller()
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
                self._controller = _empty_controller()
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

    def set_pointer_mode(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self._pointer_mode_enabled = bool(enabled)
            processor = self._processor
            controller = processor.controller.snapshot() if processor else dict(self._controller)
        setter = getattr(processor, "set_pointer_mode", None) if processor else None
        if setter:
            setter(self._pointer_mode_enabled)
        elif not self._pointer_mode_enabled:
            self.hub.publish_from_thread({
                "type": "pointer", "active": False, "pressed": False,
                "x": 0.5, "y": 0.5, "track_id": None, "handedness": None,
                "timestamp_ms": int(time.monotonic() * 1000),
            })
        return {"enabled": self._pointer_mode_enabled, "controller": controller}

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
            preview_frame_age_ms = (
                max(0, now_ms - self._last_preview_frame_at_ms)
                if self._last_preview_frame_at_ms is not None
                else None
            )
            frame_fresh = (
                self._state == "running"
                and self._latest_jpeg is not None
                and preview_frame_age_ms is not None
                and preview_frame_age_ms <= FRAME_STALE_MS
            )
            return {
                "state": self._state,
                "error": self._error,
                "pointer_mode_enabled": self._pointer_mode_enabled,
                "frame_width": self._frame_width,
                "frame_height": self._frame_height,
                "frame_ready": frame_fresh,
                "frame_fresh": frame_fresh,
                "frame_sequence": self._frame_sequence,
                "last_frame_at_ms": self._last_frame_at_ms,
                "frame_age_ms": frame_age_ms,
                "last_preview_frame_at_ms": self._last_preview_frame_at_ms,
                "preview_frame_age_ms": preview_frame_age_ms,
                "decoder": self._decoder_name,
                "reconnect_attempt": self._reconnect_attempt,
                "reconnect_count": self._reconnect_count,
                "dropped_frames": self._dropped_frames,
                "last_vision_ms": self._last_vision_ms,
                "last_jpeg_encode_ms": self._last_jpeg_encode_ms,
                "last_queue_delay_ms": self._last_queue_delay_ms,
                "last_frame_age_to_ai_ms": self._last_frame_age_to_ai_ms,
                "last_vision_at_ms": self._last_vision_at_ms,
                "preview_frame_sequence": self._preview_frame_sequence,
                "vision_frame_sequence": self._vision_frame_sequence,
                "preview_fps": self._preview_fps,
                "ai_processing_fps": self._ai_fps,
                "tracks": [track.copy() for track in self._tracks],
                "controller": controller,
                "vision": {
                    **self._vision,
                    "confidence_threshold": self._confidence_threshold,
                },
            }

    def get_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def get_recognition_settings(self) -> dict[str, float]:
        return {"gesture_confidence_threshold": self.store.get_gesture_confidence_threshold()}

    def set_gesture_confidence_threshold(self, value: float) -> dict[str, float]:
        threshold = self.store.set_gesture_confidence_threshold(value)
        with self._lock:
            self._confidence_threshold = threshold
            processor = self._processor
            if processor is not None:
                apply_threshold = getattr(processor, "set_confidence_threshold", None)
                if apply_threshold:
                    apply_threshold(threshold)
        return {"gesture_confidence_threshold": threshold}

    @staticmethod
    def _record_rate_sample(samples: deque[float], sample_at: float) -> float:
        samples.append(sample_at)
        while len(samples) > 2 and sample_at - samples[1] > FPS_WINDOW_SECONDS:
            samples.popleft()
        elapsed = samples[-1] - samples[0] if len(samples) > 1 else 0.0
        return round((len(samples) - 1) / elapsed, 1) if elapsed > 0 else 0.0

    def _prepare_preview_frame(self, frame: Any, decoded_at: float, max_width: int) -> tuple[Any, int, float]:
        import cv2

        with self._lock:
            self._decoded_frame_sequence += 1
            source_sequence = self._decoded_frame_sequence

        height, width = frame.shape[:2]
        with self._lock:
            should_encode = (
                self._last_preview_encode_at is None
                or time.monotonic() - self._last_preview_encode_at >= 1 / PREVIEW_MAX_FPS
            )
        if not should_encode:
            return frame, source_sequence, 0.0

        resize_started = time.perf_counter()
        prepared = frame
        if width > max_width:
            scale = max_width / width
            try:
                prepared = cv2.resize(frame, (max_width, max(1, round(height * scale))))
            except Exception:
                prepared = frame
        frame_resize_ms = (time.perf_counter() - resize_started) * 1000
        height, width = prepared.shape[:2]
        jpeg_started = time.perf_counter()
        try:
            encoded, jpeg = cv2.imencode(".jpg", prepared, [cv2.IMWRITE_JPEG_QUALITY, 82])
        except Exception:
            encoded, jpeg = False, None
        jpeg_encode_ms = (time.perf_counter() - jpeg_started) * 1000
        if encoded and jpeg is not None:
            preview_at = time.monotonic()
            with self._lock:
                if not self._stop_event.is_set():
                    self._latest_jpeg = jpeg.tobytes()
                    self._frame_width = width
                    self._frame_height = height
                    self._preview_frame_sequence = source_sequence
                    self._last_preview_frame_at_ms = int(time.time() * 1000)
                    self._last_jpeg_encode_ms = round(jpeg_encode_ms, 1)
                    self._last_preview_encode_at = preview_at
                    self._preview_fps = self._record_rate_sample(self._preview_times, preview_at)
        else:
            with self._lock:
                self._last_jpeg_encode_ms = round(jpeg_encode_ms, 1)
        return prepared, source_sequence, frame_resize_ms

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
                        apply_threshold = getattr(processor, "set_confidence_threshold", None)
                        if apply_threshold:
                            apply_threshold(self.store.get_gesture_confidence_threshold())
                        apply_pointer_mode = getattr(processor, "set_pointer_mode", None)
                        if apply_pointer_mode:
                            apply_pointer_mode(self._pointer_mode_enabled)
                        self._processor = processor
                        self._state = "running"
                        self._error = None
                    if was_reconnecting:
                        self.hub.publish_from_thread(
                            {"type": "stream", "state": "running", "message": "摄像头已恢复，请重新做 OK 手势锁定主控。"}
                        )

                    max_width = getattr(processor, "max_inference_width", PREVIEW_MAX_WIDTH)
                    reader = _LatestFrameReader(
                        decoder,
                        stop_event,
                        self._record_dropped_frame,
                        lambda frame, decoded_at: self._prepare_preview_frame(
                            frame, decoded_at, max_width
                        ),
                    )
                    reader.start()

                    processing_errors = 0
                    while not stop_event.is_set():
                        item = reader.read(timeout=0.5)
                        if item is None:
                            if stop_event.is_set():
                                break
                            continue
                        frame = item.frame
                        processing_started = time.monotonic()
                        queue_delay_ms = max(0.0, (processing_started - item.enqueued_at) * 1000)
                        frame_age_to_ai_ms = max(0.0, (processing_started - item.decoded_at) * 1000)

                        try:
                            result = processor.process(frame, frame_resize_ms=item.frame_resize_ms)
                        except Exception:
                            processing_errors += 1
                            if processing_errors >= MAX_CONSECUTIVE_PROCESSING_ERRORS:
                                raise _VisionProcessingFailure from None
                            continue
                        observed_vision_ms = (time.monotonic() - processing_started) * 1000
                        vision_timings = result.get("vision", {}).get("timings", {})
                        vision_ms = float(vision_timings.get("full_vision_ms", observed_vision_ms))
                        processing_errors = 0
                        now_ms = int(time.time() * 1000)
                        with self._lock:
                            self._frame_sequence += 1
                            self._vision_frame_sequence = item.source_sequence
                            self._last_frame_at_ms = now_ms
                            self._last_vision_at_ms = now_ms
                            self._tracks = result["tracks"]
                            self._controller = result["controller"]
                            self._vision = result.get("vision", self._vision)
                            self._last_vision_ms = round(vision_ms, 1)
                            self._last_queue_delay_ms = round(queue_delay_ms, 1)
                            self._last_frame_age_to_ai_ms = round(frame_age_to_ai_ms, 1)
                            self._ai_fps = self._record_rate_sample(self._ai_times, time.monotonic())
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
                self._controller = _empty_controller()
                self._latest_jpeg = None
                self._last_frame_at_ms = None
                self._last_preview_frame_at_ms = None
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
            self._last_preview_frame_at_ms = None
            self._last_vision_at_ms = None
            self._last_vision_ms = None
            self._last_jpeg_encode_ms = None
            self._last_queue_delay_ms = None
            self._last_frame_age_to_ai_ms = None
            self._preview_times.clear()
            self._ai_times.clear()
            self._preview_fps = 0.0
            self._ai_fps = 0.0
            self._last_preview_encode_at = None
            self._vision_frame_sequence = 0
            self._tracks = []
            self._vision = _empty_vision()
            self._controller = _empty_controller()
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
