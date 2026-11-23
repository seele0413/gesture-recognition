"""Build a Windows x64 portable runtime plus a source archive from this checkout.

Run with the tested .venv interpreter. Copies production distributions using their
installed RECORDs, not a non-relocatable virtualenv. No private .env is copied.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import platform
import shutil
import sqlite3
import struct
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"
NAME = "GestureControl"
DIRECTORIES = ("app", "web", "scripts", "tests", ".github", "docs")
ROOT_FILES = (
    "README.md", "WORKFLOWS.md", "MODEL_SOURCES.md", "THIRD_PARTY_NOTICES.md",
    "requirements.txt", "requirements-dev.txt", "setup.ps1", "run.ps1",
    "launcher.py", "START.cmd", "CHECK.cmd", "BACKUP.cmd", "先读我.txt", ".env.example", ".gitignore",
)


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def production_distributions() -> list:
    installed = {canonicalize_name(dist.metadata["Name"]): dist for dist in metadata.distributions()}
    queue = [Requirement(line.strip()) for line in (ROOT / "requirements.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]
    selected = {}
    visited = set()
    while queue:
        requirement = queue.pop()
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        name = canonicalize_name(requirement.name)
        key = (name, tuple(sorted(requirement.extras)))
        if key in visited:
            continue
        visited.add(key)
        dist = installed[name]
        if requirement.specifier and not requirement.specifier.contains(dist.version):
            raise RuntimeError(f"Installed {name}=={dist.version} does not satisfy {requirement}")
        selected[name] = dist
        for value in dist.requires or []:
            child = Requirement(value)
            if child.marker and not any(child.marker.evaluate({"extra": extra}) for extra in ["", *requirement.extras]):
                continue
            child.marker = None
            queue.append(child)
    return [selected[name] for name in sorted(selected)]


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "*.log"))


def copy_source(target: Path) -> None:
    target.mkdir(parents=True)
    for name in DIRECTORIES:
        copy_tree(ROOT / name, target / name)
    for name in ROOT_FILES:
        if (ROOT / name).is_file():
            shutil.copy2(ROOT / name, target / name)
    for name in ("data", "media", "models"):
        (target / name).mkdir(exist_ok=True)
        (target / name / ".gitkeep").write_text("", encoding="utf-8")


def copy_distribution(dist, destination: Path) -> None:
    base = Path(dist.locate_file("")).resolve()
    for record in dist.files or []:
        source = Path(dist.locate_file(record)).resolve()
        if not source.is_relative_to(base) or not source.is_file() or "__pycache__" in source.parts:
            continue
        if source.suffix in (".pyc", ".pyo"):
            continue
        target = destination / source.relative_to(base)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def snapshot_database(target: Path) -> dict:
    source_path = ROOT / "data/identities.sqlite3"
    with closing(sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(target)) as output:
            source.backup(output)
    with closing(sqlite3.connect(target)) as output:
        output.execute("PRAGMA journal_mode=DELETE")
        output.execute("DELETE FROM workflow_step_runs")
        output.execute("DELETE FROM workflow_runs")
        output.execute("DELETE FROM gesture_events")
        output.execute("DELETE FROM controller_sessions")
        # Preserve saved workflows, enablement, versions, display pages and settings.
        counts = {table: output.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("workflows", "workflow_versions", "display_pages")}
        output.commit()
        output.execute("VACUUM")
    return counts


def prepare(output: Path, extra_site: Path | None) -> Path:
    if sys.platform != "win32" or struct.calcsize("P") != 8 or sys.version_info[:2] != (3, 12):
        raise RuntimeError("Build with the tested Windows x64 CPython 3.12 environment")
    output.mkdir(parents=True, exist_ok=False)
    portable = output / f"{NAME}-Windows-x64-{VERSION}"
    source = output / f"{NAME}-Source-{VERSION}"
    for target in (portable, source):
        copy_source(target)
    runtime = portable / "runtime"
    base = Path(sys.base_prefix)
    runtime.mkdir()
    for item in base.iterdir():
        if item.name in ("include", "libs", "Scripts"):
            continue
        if item.is_dir():
            if item.name == "Lib":
                shutil.copytree(item, runtime / item.name, ignore=shutil.ignore_patterns("site-packages", "__pycache__", "*.pyc", "test", "tests", "idlelib", "ensurepip"))
            else:
                copy_tree(item, runtime / item.name)
        else:
            shutil.copy2(item, runtime / item.name)
    site = runtime / "Lib/site-packages"
    site.mkdir()
    distributions = production_distributions()
    for dist in distributions:
        copy_distribution(dist, site)
    if extra_site:
        for dist in metadata.distributions(path=[str(extra_site)]):
            copy_distribution(dist, site)
            distributions.append(dist)
    lock = "# Validated Windows x64 CPython 3.12 production dependency snapshot\n" + "\n".join(sorted(f"{dist.metadata['Name']}=={dist.version}" for dist in distributions)) + "\n"
    for target in (portable, source):
        (target / "requirements-lock.txt").write_text(lock, encoding="utf-8")
    for name in ("gesture_recognizer.task", "pose_landmarker_lite.task"):
        shutil.copy2(ROOT / "models" / name, portable / "models" / name)
    shutil.copy2(ROOT / "media/company-promo.mp4", portable / "media/company-promo.mp4")
    counts = snapshot_database(portable / "data/identities.sqlite3")
    # The source package also carries the saved, cleaned configuration snapshot.
    shutil.copy2(portable / "data/identities.sqlite3", source / "data/identities.sqlite3")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    release = {
        "product": NAME, "version": VERSION, "built_at": datetime.now(timezone.utc).isoformat(),
        "source_branch": "codex/usage-flow", "source_base_commit": commit,
        "source_includes_uncommitted_changes": True,
        "python": platform.python_version(), "runtime_build": (base / "BUILD").read_text().strip(),
        "runtime_origin": "https://docs.astral.sh/python-build-standalone/",
        "configuration_snapshot": counts,
        "excluded": ["private .env and API keys", "RTSP credentials", "development logs", "temporary identity and gesture events", "workflow run logs", "virtualenv and Git metadata"],
        "packages": sorted([{"name": dist.metadata["Name"], "version": dist.version} for dist in distributions], key=lambda item: item["name"].lower()),
    }
    licenses = portable / "licenses"
    licenses.mkdir()
    shutil.copy2(base / "LICENSE.txt", licenses / "Python-LICENSE.txt")
    for dist in distributions:
        for record in dist.files or []:
            if any(token in str(record).lower() for token in ("license", "copying", "notice")):
                origin = Path(dist.locate_file(record))
                if origin.is_file():
                    relative = Path(str(record).replace("..", "_"))
                    destination = licenses / canonicalize_name(dist.metadata["Name"]) / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(origin, destination)
    for target in (portable, source):
        (target / "RELEASE.json").write_text(json.dumps(release, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "build-state.json").write_text(json.dumps({"portable": portable.name, "source": source.name}), encoding="utf-8")
    print(f"Prepared {portable}\nProduction packages: {len(distributions)}\nSaved configuration: {counts}", flush=True)
    return output


def finalize(output: Path, documents: Path | None) -> None:
    state = json.loads((output / "build-state.json").read_text(encoding="utf-8"))
    hashes = []
    for key in ("portable", "source"):
        target = output / state[key]
        # Refresh docs and source files so a final review is reflected in both ZIPs.
        for name in DIRECTORIES:
            copy_tree(ROOT / name, target / name)
        for name in ROOT_FILES:
            if (ROOT / name).is_file():
                shutil.copy2(ROOT / name, target / name)
        if documents:
            for document in documents.iterdir():
                if document.is_file() and document.suffix in (".docx", ".pdf"):
                    shutil.copy2(document, target / "docs" / document.name)
        entries = []
        for path in sorted(target.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            relative = path.relative_to(target).as_posix()
            # Local launch/test artifacts are never part of a delivery.
            if relative == ".env" or relative.endswith(("-wal", "-shm")) or relative.startswith(("logs/", "backups/", "data/usage-flow-qa/")) or relative in ("data/service.json", "data/launcher.lock", "RELEASE-MANIFEST.json"):
                continue
            entries.append({"path": relative, "size": path.stat().st_size, "sha256": sha256(path), "mutable": relative.startswith("data/")})
        manifest = target / "RELEASE-MANIFEST.json"
        manifest.write_text(json.dumps({"format": 1, "files": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
        archive = output / (target.name + ".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
            for entry in entries:
                zipped.write(target / entry["path"], target.name + "/" + entry["path"])
            zipped.write(manifest, target.name + "/RELEASE-MANIFEST.json")
        value = sha256(archive)
        hashes.append(value + "  " + archive.name)
        print(f"Created {archive.name}: {archive.stat().st_size / 1024 ** 2:.1f} MiB, SHA256 {value}", flush=True)
    (output / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="ascii")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "release" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--extra-site", type=Path)
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--documents", type=Path)
    args = parser.parse_args()
    if args.finalize:
        finalize(args.output.resolve(), args.documents)
    else:
        prepare(args.output.resolve(), args.extra_site)
