from __future__ import annotations

import json
import socket
import signal
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

import launcher
from launcher import InstanceLock, backup_configuration, digest, reserve_port, verify_files


class ReleaseTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(signal, "SIGBREAK"), "Windows console signal")
    def test_ctrl_break_runs_cleanup_and_restores_signal_handler(self):
        original = signal.getsignal(signal.SIGBREAK)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "models").mkdir()
            (root / "data").mkdir()
            (root / ".env.example").write_text("", encoding="utf-8")
            for name in ("gesture_recognizer.task", "pose_landmarker_lite.task"):
                (root / "models" / name).touch()
            state = root / "data/service.json"
            state.write_text("{}", encoding="utf-8")
            fake = Mock(started=False, should_exit=True)

            def interrupt(**_kwargs):
                self.assertIs(signal.getsignal(signal.SIGBREAK), signal.default_int_handler)
                signal.getsignal(signal.SIGBREAK)(signal.SIGBREAK, None)

            fake.run.side_effect = interrupt
            previous_directory = Path.cwd()
            try:
                with patch.object(launcher, "ROOT", root), patch("uvicorn.Config"), patch("uvicorn.Server", return_value=fake):
                    with self.assertRaises(KeyboardInterrupt):
                        launcher.serve(8000, True)
                self.assertFalse(state.exists())
                next_lock = InstanceLock(root / "data/launcher.lock")
                self.assertTrue(next_lock.acquire())
                next_lock.close()
            finally:
                import os
                os.chdir(previous_directory)
        self.assertEqual(signal.getsignal(signal.SIGBREAK), original)

    def test_port_reservation_skips_an_occupied_port_and_is_loopback_only(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            port = occupied.getsockname()[1]
            occupied.listen()
            if port == 65535:
                self.skipTest("No following port available")
            listener = reserve_port(port)
            try:
                self.assertEqual(listener.getsockname()[0], "127.0.0.1")
                self.assertGreater(listener.getsockname()[1], port)
            finally:
                listener.close()

    def test_instance_lock_releases_after_close(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "instance.lock"
            first = InstanceLock(path)
            self.assertTrue(first.acquire())
            try:
                self.assertFalse(InstanceLock(path).acquire())
            finally:
                first.close()
            third = InstanceLock(path)
            self.assertTrue(third.acquire())
            third.close()

    def test_online_backup_is_consistent_and_contains_only_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            (root / "app").mkdir()
            with closing(sqlite3.connect(root / "data/identities.sqlite3")) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE example(value)")
                db.execute("INSERT INTO example VALUES ('saved')")
                db.commit()
                (root / ".env").write_text("EXAMPLE=local", encoding="utf-8")
                (root / "app/settings.py").write_text("# config", encoding="utf-8")
                (root / "data/unrelated.log").write_text("temporary", encoding="utf-8")
                backup = backup_configuration(root)
            with zipfile.ZipFile(backup) as archive:
                self.assertEqual(set(archive.namelist()), {"data/identities.sqlite3", ".env", "app/settings.py", "RESTORE.txt"})
                copied = root / "copied.sqlite3"
                copied.write_bytes(archive.read("data/identities.sqlite3"))
            with closing(sqlite3.connect(copied)) as db:
                self.assertEqual(db.execute("SELECT value FROM example").fetchone()[0], "saved")

    def test_manifest_accepts_mutable_data_but_detects_modified_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = root / "code.py"
            code.write_text("pass", encoding="utf-8")
            entries = [{"path": "code.py", "sha256": digest(code)}, {"path": "data/example", "sha256": "unused", "mutable": True}]
            (root / "RELEASE-MANIFEST.json").write_text(json.dumps({"files": entries}), encoding="utf-8")
            verify_files(root)
            code.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "code.py"):
                verify_files(root)

    def test_manifest_rejects_paths_outside_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "RELEASE-MANIFEST.json").write_text(json.dumps({"files": [{"path": "../outside", "sha256": "unused"}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_files(root)
