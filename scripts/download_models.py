from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models"
MODELS = (
    (
        "gesture_recognizer.task",
        "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task",
        "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482",
    ),
    (
        "pose_landmarker_lite.task",
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
        "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(name: str, url: str, expected: str) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    destination = MODEL_DIR / name
    if destination.is_file() and sha256(destination) == expected:
        print(f"Verified {name}")
        return

    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "rtsp-gesture-control/1.0"})
    try:
        print(f"Downloading {name}...")
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        actual = sha256(temporary)
        if actual != expected:
            raise RuntimeError(f"{name} 的 SHA-256 不匹配；已拒绝该文件")
        temporary.replace(destination)
        print(f"Downloaded and verified {name}")
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    try:
        for name, url, expected in MODELS:
            download(name, url, expected)
    except Exception as error:
        print(f"Model setup failed: {error}", file=sys.stderr)
        return 1
    print(f"All models are ready in {MODEL_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
