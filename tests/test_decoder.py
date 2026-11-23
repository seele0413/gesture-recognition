import unittest
from types import SimpleNamespace

import numpy as np

from app.decoder import PyAVDecoder


class FakeFrame:
    def to_ndarray(self, *, format):
        if format != "bgr24":
            raise ValueError("unexpected pixel format")
        return np.zeros((2, 2, 3), dtype=np.uint8)


class FakeContainer:
    def __init__(self, *, video_streams=None, frames=None):
        streams = [SimpleNamespace(index=2)] if video_streams is None else video_streams
        self.streams = SimpleNamespace(video=streams)
        self.frames = frames if frames is not None else [FakeFrame()]
        self.decoded_stream = None
        self.closed = False

    def decode(self, *, video):
        self.decoded_stream = video
        return iter(self.frames)

    def close(self):
        self.closed = True


class FakeAV:
    def __init__(self, container):
        self.container = container
        self.args = None

    def open(self, *args, **kwargs):
        self.args = (args, kwargs)
        return self.container


class FailingAV:
    def open(self, url, **_kwargs):
        raise RuntimeError(f"unable to open {url}")


class PyAVDecoderTests(unittest.TestCase):
    def test_opens_rtsp_over_tcp_with_bounded_timeouts_and_converts_bgr(self):
        container = FakeContainer()
        fake_av = FakeAV(container)
        decoder = PyAVDecoder(
            "rtsp://camera.local/live", av_module=fake_av, open_timeout=3, read_timeout=4
        )
        args, kwargs = fake_av.args
        self.assertEqual(args[0], "rtsp://camera.local/live")
        self.assertEqual(kwargs["timeout"], (3, 4))
        self.assertEqual(kwargs["options"]["rtsp_transport"], "tcp")
        self.assertEqual(container.decoded_stream, 2)
        ok, image = decoder.read()
        self.assertTrue(ok)
        self.assertEqual(image.shape, (2, 2, 3))
        self.assertEqual(image.dtype, np.uint8)
        self.assertEqual(decoder.read(), (False, None))
        decoder.close()
        self.assertTrue(container.closed)
        self.assertEqual(decoder.read(), (False, None))

    def test_missing_video_track_closes_container(self):
        container = FakeContainer(video_streams=[])
        with self.assertRaisesRegex(RuntimeError, "没有视频轨道"):
            PyAVDecoder("rtsp://camera.local/live", av_module=FakeAV(container))
        self.assertTrue(container.closed)

    def test_open_failure_does_not_retain_rtsp_credentials_in_error(self):
        with self.assertRaises(RuntimeError) as raised:
            PyAVDecoder("rtsp://operator:s3cret@camera.local/live", av_module=FailingAV())
        self.assertNotIn("operator", str(raised.exception))
        self.assertNotIn("s3cret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
