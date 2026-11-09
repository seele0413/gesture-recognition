from __future__ import annotations

from typing import Any


class PyAVDecoder:
    """Decode a low-latency RTSP video stream to OpenCV-compatible BGR frames."""

    name = "PyAV / FFmpeg"

    def __init__(
        self,
        url: str,
        *,
        av_module: Any = None,
        open_timeout: float = 5.0,
        read_timeout: float = 5.0,
    ):
        if av_module is None:
            import av as av_module

        open_args = {
            "mode": "r",
            "options": {
                "rtsp_transport": "tcp",
                "rw_timeout": str(int(read_timeout * 1_000_000)),
                "max_delay": "500000",
            },
            "timeout": (open_timeout, read_timeout),
        }
        try:
            capture_factory = getattr(getattr(av_module, "logging", None), "Capture", None)
            if capture_factory:
                with capture_factory():
                    self._container = av_module.open(url, **open_args)
            else:
                self._container = av_module.open(url, **open_args)
        except Exception:
            raise RuntimeError("RTSP 视频流打开失败，请检查地址、账号密码和网络。") from None
        streams = self._container.streams.video
        if not streams:
            self._container.close()
            raise RuntimeError("RTSP 地址中没有视频轨道")
        self._stream = streams[0]
        self._frames = iter(self._container.decode(video=self._stream.index))
        self._closed = False

    def read(self) -> tuple[bool, Any]:
        if self._closed:
            return False, None
        try:
            frame = next(self._frames)
        except StopIteration:
            return False, None
        return True, frame.to_ndarray(format="bgr24")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._container.close()

    def release(self) -> None:
        self.close()
