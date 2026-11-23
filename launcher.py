"""Relocatable Windows release launcher; the application remains ordinary Python source."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import logging
import os
import shutil
import signal
import socket
import sqlite3
import struct
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile
from datetime import datetime
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# -I isolates the bundled interpreter from the user's Python installation.
sys.path.insert(0, str(ROOT))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def reserve_port(start: int = 8000, attempts: int = 100) -> socket.socket:
    if not 1 <= start <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    for port in range(start, min(65536, start + attempts)):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(128)
            listener.setblocking(False)
            return listener
        except OSError:
            listener.close()
    raise RuntimeError(f"No available local port starting at {start}")


class InstanceLock:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        if path.stat().st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        self.acquired = False

    def acquire(self) -> bool:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
        except OSError:
            self.file.close()
        return self.acquired

    def close(self) -> None:
        if self.acquired:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()
            self.acquired = False


def backup_configuration(root: Path = ROOT) -> Path:
    """SQLite online backup produces a consistent copy even while the server runs."""
    database = root / "data" / "identities.sqlite3"
    if not database.is_file():
        raise FileNotFoundError("No saved database found; start the application first")
    destination = root / "backups"
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / ("configuration-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".zip")
    with tempfile.TemporaryDirectory(prefix="gesture-backup-") as temporary:
        snapshot = Path(temporary) / "identities.sqlite3"
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            output.write(snapshot, "data/identities.sqlite3")
            for relative in (".env", "app/settings.py"):
                source = root / relative
                if source.is_file():
                    output.write(source, relative)
            output.writestr("RESTORE.txt", "Stop the server before restoring. Restore data/identities.sqlite3 and .env to the release root. Review app/settings.py before replacing it. Media files and browser-local calibration are not included. The .env file may contain your API key.\n")
    return archive


def verify_files(root: Path = ROOT) -> None:
    manifest = json.loads((root / "RELEASE-MANIFEST.json").read_text(encoding="utf-8"))
    checked = 0
    for entry in manifest["files"]:
        if entry.get("mutable"):
            continue
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Invalid manifest path")
        if not path.is_file() or digest(path) != entry["sha256"]:
            raise RuntimeError("File verification failed: " + entry["path"])
        checked += 1
    print(f"Verified {checked} application, runtime, model and media files.")


def health_check(vision: bool = False) -> int:
    from scripts.download_models import MODELS
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise RuntimeError("The portable release requires Windows x64")
    for module in ("fastapi", "uvicorn", "av", "cv2", "numpy", "mediapipe", "multipart", "pypdf"):
        importlib.import_module(module)
        print("OK import " + module)
    for name, _url, expected in MODELS:
        if digest(ROOT / "models" / name) != expected:
            raise RuntimeError("Model checksum mismatch: " + name)
        print("OK model " + name)
    if not (ROOT / "media/company-promo.mp4").is_file():
        raise FileNotFoundError("Missing media/company-promo.mp4")
    print("OK local promotional video")
    try:
        import pythoncom
        import win32com.client
        print("OK PowerPoint COM bridge (Microsoft PowerPoint must be installed separately)")
    except ImportError:
        print("OPTIONAL: pywin32 is not installed; PowerPoint actions are unavailable")
    if vision:
        import numpy as np
        from app.database import ControlStore
        from app.vision import VisionProcessor
        with tempfile.TemporaryDirectory(prefix="gesture-model-check-") as temporary:
            store = ControlStore(Path(temporary) / "check.sqlite3")
            processor = VisionProcessor(store, lambda _event: None)
            try:
                processor.process(np.zeros((480, 640, 3), dtype=np.uint8))
            finally:
                processor.close()
        print("OK both MediaPipe models initialized and processed a blank frame")
    print("CHECK PASSED. RTSP and physical gesture acceptance are performed on site.")
    return 0


def serve(port: int, no_browser: bool) -> int:
    import uvicorn
    os.chdir(ROOT)
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "logs").mkdir(exist_ok=True)
    lock = InstanceLock(ROOT / "data/launcher.lock")
    if not lock.acquire():
        print("This release is already running. Use the existing server window.")
        state_path = ROOT / "data/service.json"
        if state_path.is_file():
            print("Website: " + json.loads(state_path.read_text(encoding="utf-8"))["url"])
        return 0
    listener = None
    previous_break_handler = None
    state_path = ROOT / "data/service.json"
    try:
        if hasattr(signal, "SIGBREAK"):
            # Uvicorn re-raises captured signals after graceful shutdown. The
            # Windows default for Ctrl+Break terminates before our finally block.
            previous_break_handler = signal.signal(signal.SIGBREAK, signal.default_int_handler)
        if not (ROOT / ".env").exists():
            shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
        for name in ("gesture_recognizer.task", "pose_landmarker_lite.task"):
            if not (ROOT / "models" / name).is_file():
                raise FileNotFoundError("Missing model; extract the complete release again: " + name)
        listener = reserve_port(port)
        actual_port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{actual_port}"
        log_config = {
            "version": 1, "disable_existing_loggers": False,
            "formatters": {"standard": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "standard", "stream": "ext://sys.stdout"},
                "file": {"class": "logging.handlers.RotatingFileHandler", "formatter": "standard", "filename": str(ROOT / "logs/server.log"), "maxBytes": 5_000_000, "backupCount": 3, "encoding": "utf-8"},
            },
            "loggers": {"uvicorn": {"handlers": ["console", "file"], "level": "INFO", "propagate": False}},
        }
        config = uvicorn.Config("app.main:app", host="127.0.0.1", port=actual_port, access_log=False, log_config=log_config)
        server = uvicorn.Server(config)

        def ready() -> None:
            while not server.started and not server.should_exit:
                time.sleep(0.1)
            if not server.started:
                return
            state_path.write_text(json.dumps({"pid": os.getpid(), "url": url}, indent=2), encoding="utf-8")
            print("\nWebsite: " + url + "\nKeep this window open. Press Ctrl+C to stop.\n", flush=True)
            if not no_browser:
                try:
                    webbrowser.open(url)
                except Exception:
                    print("Open the website above in Microsoft Edge or Google Chrome.")

        threading.Thread(target=ready, name="release-ready", daemon=True).start()
        server.run(sockets=[listener])
        return 0 if server.started else 1
    finally:
        if listener is not None:
            listener.close()
        state_path.unlink(missing_ok=True)
        lock.close()
        if previous_break_handler is not None:
            signal.signal(signal.SIGBREAK, previous_break_handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Gesture Control Windows launcher")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-vision", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify_files()
        return 0
    if args.check or args.check_vision:
        return health_check(args.check_vision)
    if args.backup:
        print("Backup saved: " + str(backup_configuration()))
        return 0
    return serve(args.port, args.no_browser)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as error:
        print("FAILED: " + str(error), file=sys.stderr)
        print("See the Windows deployment guide and logs/server.log.", file=sys.stderr)
        raise SystemExit(1)
