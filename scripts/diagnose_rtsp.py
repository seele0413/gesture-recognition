from __future__ import annotations

import argparse
import getpass
import json
import statistics
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def image_info(image: Any) -> dict[str, Any]:
    import numpy as np

    array = np.asarray(image)
    return {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "strides": list(array.strides),
        "c_contiguous": bool(array.flags.c_contiguous),
        "min_value": int(array.min()) if array.size else None,
        "max_value": int(array.max()) if array.size else None,
    }


def frame_info(frame: Any) -> dict[str, Any]:
    pixel_format = getattr(getattr(frame, "format", None), "name", None)
    return {
        "width": int(frame.width),
        "height": int(frame.height),
        "pixel_format": pixel_format,
        "plane_line_sizes": [int(plane.line_size) for plane in frame.planes],
        "pts": int(frame.pts) if frame.pts is not None else None,
        "time_base": str(frame.time_base) if frame.time_base is not None else None,
        "key_frame": bool(frame.key_frame),
        "is_corrupt": bool(getattr(frame, "is_corrupt", False)),
    }


def timing_summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min_ms": round(min(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "max_ms": round(max(values), 3),
    }


def timed_frames(frames: Any, timings: list[float]):
    iterator = iter(frames)
    while True:
        started = time.perf_counter()
        try:
            frame = next(iterator)
        except StopIteration:
            return
        timings.append((time.perf_counter() - started) * 1000)
        yield frame


def main() -> int:
    parser = argparse.ArgumentParser(
        description="诊断 RTSP 解码、MediaPipe 处理和 JPEG 编码；不会把 RTSP 地址写入报告。"
    )
    parser.add_argument("--frames", type=int, default=120, help="采集的有效帧数，默认 120")
    parser.add_argument("--samples", type=int, default=8, help="每个阶段最多保存的抽样图片数，默认 8")
    parser.add_argument("--with-vision", action="store_true", help="同时运行项目的 VisionProcessor，需要已下载模型")
    parser.add_argument("--discard-corrupt", action="store_true", help="启用 FFmpeg discardcorrupt，默认保持 main 当前解码选项")
    parser.add_argument("--output", type=Path, help="报告输出目录；默认 diagnostics/时间戳")
    args = parser.parse_args()

    if args.frames < 1 or args.samples < 1:
        parser.error("--frames 和 --samples 必须大于 0")

    url = getpass.getpass("请输入 RTSP 地址（输入不会显示）：").strip()
    if not url:
        print("未输入 RTSP 地址。")
        return 2

    try:
        import av
        import cv2
        import numpy as np
    except Exception as error:
        print(f"诊断依赖导入失败：{type(error).__name__}")
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output or (PROJECT_ROOT / "diagnostics" / f"rtsp_{stamp}")
    output_dir.mkdir(parents=True, exist_ok=True)

    options = {
        "rtsp_transport": "tcp",
        "rw_timeout": "5000000",
        "max_delay": "500000",
    }
    if args.discard_corrupt:
        options["fflags"] = "discardcorrupt"

    report: dict[str, Any] = {
        "created_at": datetime.now().astimezone().isoformat(),
        "connection": {
            "transport": "tcp",
            "discard_corrupt": bool(args.discard_corrupt),
            "requested_valid_frames": args.frames,
            "requested_samples": args.samples,
            "vision_enabled": bool(args.with_vision),
        },
        "runtime": {
            "pyav": av.__version__,
            "ffmpeg_libraries": {name: str(version) for name, version in av.library_versions.items()},
            "opencv": cv2.__version__,
            "numpy": np.__version__,
        },
        "frames": [],
        "failures": {
            "corrupt_frames": 0,
            "bgr_conversion": 0,
            "vision_processing": 0,
            "jpeg_encode": 0,
            "jpeg_decode": 0,
        },
        "vision_initialization_error": None,
        "decode_loop_error": None,
    }

    try:
        container = av.open(
            url,
            mode="r",
            options=options,
            timeout=(5.0, 5.0),
        )
    except Exception as error:
        print(f"RTSP 打开失败：{type(error).__name__}。报告不会包含地址或账号密码。")
        return 2

    processor = None
    store = None
    session_id = "diagnostic-" + uuid.uuid4().hex
    pyav_decode_next_ms: list[float] = []
    decode_to_bgr_ms: list[float] = []
    vision_ms: list[float] = []
    jpeg_encode_ms: list[float] = []
    jpeg_decode_ms: list[float] = []
    valid_frames = 0
    saved_samples = 0
    sample_interval = max(1, args.frames // args.samples)

    try:
        streams = container.streams.video
        if not streams:
            print("RTSP 地址中没有视频轨道。")
            return 2

        stream = streams[0]
        codec = stream.codec_context
        report["stream"] = {
            "codec": codec.name,
            "width": int(codec.width),
            "height": int(codec.height),
            "codec_pixel_format": codec.format.name if codec.format else None,
            "average_rate": str(stream.average_rate) if stream.average_rate else None,
            "time_base": str(stream.time_base) if stream.time_base else None,
        }

        if args.with_vision:
            try:
                from app.database import ControlStore
                from app.settings import MODEL_DIR
                from app.vision import VisionProcessor

                store = ControlStore(output_dir / "diagnostic.sqlite3")
                store.begin_session(session_id, int(time.time() * 1000))
                processor = VisionProcessor(
                    store,
                    lambda _event: None,
                    MODEL_DIR,
                    session_id,
                )
            except Exception as error:
                report["vision_initialization_error"] = type(error).__name__
                processor = None
                print(f"视觉模型初始化失败：{type(error).__name__}；仍将继续测试解码和 JPEG。")

        try:
            for decoded_index, frame in enumerate(timed_frames(container.decode(video=stream.index), pyav_decode_next_ms)):
                if bool(getattr(frame, "is_corrupt", False)):
                    report["failures"]["corrupt_frames"] += 1
                    continue

                conversion_started = time.perf_counter()
                try:
                    bgr = frame.to_ndarray(format="bgr24")
                except Exception as error:
                    report["failures"]["bgr_conversion"] += 1
                    report["frames"].append({
                        "decoded_index": decoded_index,
                        "bgr_conversion_error": type(error).__name__,
                    })
                    continue
                conversion_elapsed = (time.perf_counter() - conversion_started) * 1000
                decode_to_bgr_ms.append(conversion_elapsed)

                if (
                    not isinstance(bgr, np.ndarray)
                    or bgr.ndim != 3
                    or bgr.shape[2] != 3
                    or bgr.dtype != np.uint8
                    or bgr.shape[0] < 2
                    or bgr.shape[1] < 2
                ):
                    report["failures"]["bgr_conversion"] += 1
                    report["frames"].append({
                        "decoded_index": decoded_index,
                        "bgr_conversion_error": "unexpected_array_shape_or_dtype",
                        "bgr": image_info(bgr),
                    })
                    continue

                valid_frames += 1
                sample_this_frame = (
                    saved_samples < args.samples
                    and (valid_frames - 1) % sample_interval == 0
                )
                record: dict[str, Any] = {
                    "valid_index": valid_frames,
                    "decoded_index": decoded_index,
                    "source_frame": frame_info(frame),
                    "bgr": image_info(bgr),
                    "pyav_decode_next_ms": round(pyav_decode_next_ms[decoded_index], 3),
                    "bgr_conversion_ms": round(conversion_elapsed, 3),
                }

                if sample_this_frame:
                    raw_path = output_dir / f"sample_{saved_samples:02d}_raw_bgr.png"
                    record["raw_png_saved"] = bool(cv2.imwrite(str(raw_path), bgr))
                    record["raw_png"] = raw_path.name

                processed = bgr
                if processor is not None:
                    vision_started = time.perf_counter()
                    try:
                        result = processor.process(bgr.copy())
                        processed = result["frame"]
                        elapsed = (time.perf_counter() - vision_started) * 1000
                        vision_ms.append(elapsed)
                        record["vision_ms"] = round(elapsed, 3)
                        record["processed"] = image_info(processed)
                    except Exception as error:
                        report["failures"]["vision_processing"] += 1
                        record["vision_error"] = type(error).__name__
                    if sample_this_frame and "vision_error" not in record:
                        processed_path = output_dir / f"sample_{saved_samples:02d}_vision.png"
                        record["vision_png_saved"] = bool(cv2.imwrite(str(processed_path), processed))
                        record["vision_png"] = processed_path.name

                encode_started = time.perf_counter()
                try:
                    encoded, jpeg = cv2.imencode(
                        ".jpg",
                        processed,
                        [cv2.IMWRITE_JPEG_QUALITY, 82],
                    )
                except Exception as error:
                    encoded, jpeg = False, None
                    record["jpeg_encode_error"] = type(error).__name__
                encode_elapsed = (time.perf_counter() - encode_started) * 1000
                jpeg_encode_ms.append(encode_elapsed)
                record["jpeg_encode_ms"] = round(encode_elapsed, 3)

                if not encoded or jpeg is None:
                    report["failures"]["jpeg_encode"] += 1
                else:
                    record["jpeg_bytes"] = int(jpeg.size)
                    decode_started = time.perf_counter()
                    try:
                        roundtrip = cv2.imdecode(jpeg, cv2.IMREAD_COLOR)
                    except Exception as error:
                        roundtrip = None
                        record["jpeg_decode_error"] = type(error).__name__
                    decode_elapsed = (time.perf_counter() - decode_started) * 1000
                    jpeg_decode_ms.append(decode_elapsed)
                    record["jpeg_decode_ms"] = round(decode_elapsed, 3)

                    if roundtrip is None or roundtrip.size == 0:
                        report["failures"]["jpeg_decode"] += 1
                    else:
                        record["jpeg_roundtrip"] = image_info(roundtrip)
                        if sample_this_frame:
                            jpeg_path = output_dir / f"sample_{saved_samples:02d}_jpeg_roundtrip.png"
                            record["jpeg_png_saved"] = bool(cv2.imwrite(str(jpeg_path), roundtrip))
                            record["jpeg_png"] = jpeg_path.name

                report["frames"].append(record)
                if sample_this_frame:
                    saved_samples += 1
                if valid_frames >= args.frames:
                    break
        except Exception as error:
            report["decode_loop_error"] = type(error).__name__
    finally:
        if processor is not None:
            try:
                processor.close()
            except Exception:
                pass
        try:
            container.close()
        except Exception:
            pass

    report["summary"] = {
        "valid_frames": valid_frames,
        "saved_samples": saved_samples,
        "pyav_decode_next": timing_summary(pyav_decode_next_ms),
        "bgr_conversion": timing_summary(decode_to_bgr_ms),
        "vision_processing": timing_summary(vision_ms),
        "jpeg_encode": timing_summary(jpeg_encode_ms),
        "jpeg_decode": timing_summary(jpeg_decode_ms),
    }
    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"有效帧：{valid_frames}；保存样本：{saved_samples}")
    print(f"报告：{report_path.resolve()}")
    print(f"图片目录：{output_dir.resolve()}")
    print("RTSP 地址和账号密码不会写入报告。")
    if valid_frames == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
