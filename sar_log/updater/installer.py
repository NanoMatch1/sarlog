"""Staging, applying and rolling back updates in the install folder.

Folder layout (all inside the install folder)::

    data/                 the user's database and backups   never touched
    .venv/                Python environment                 never touched
    updates/
        downloads/        downloaded release zips
        staged/           unpacked release waiting to be applied
        previous/         the code that was replaced last time (for rollback)
        pending.json      what to do at next start: install or rollback
        installed.json    which top-level entries the updater put in place
        last_result.json  outcome of the last apply, shown on the updates page

Applying is a series of renames within one disk, so it is fast and each step
can be undone. If anything fails part-way, every rename done so far is
reversed and the old version keeps running.
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from sar_log.updater.versions import Version, parse_version, read_installed_version

# Top-level names an update never moves, replaces or deletes.
PROTECTED_NAMES = frozenset({"data", ".venv", "venv", "updates", ".git"})

ACTION_INSTALL = "install"
ACTION_ROLLBACK = "rollback"


class UpdateError(Exception):
    """An update could not be staged or applied. The message is for the user."""


@dataclass(frozen=True)
class InstallLayout:
    install_directory: Path

    @property
    def updates_directory(self) -> Path:
        return self.install_directory / "updates"

    @property
    def downloads_directory(self) -> Path:
        return self.updates_directory / "downloads"

    @property
    def staged_directory(self) -> Path:
        return self.updates_directory / "staged"

    @property
    def previous_directory(self) -> Path:
        return self.updates_directory / "previous"

    @property
    def pending_path(self) -> Path:
        return self.updates_directory / "pending.json"

    @property
    def installed_manifest_path(self) -> Path:
        return self.updates_directory / "installed.json"

    @property
    def previous_manifest_path(self) -> Path:
        return self.updates_directory / "previous.json"

    @property
    def last_result_path(self) -> Path:
        return self.updates_directory / "last_result.json"

    def is_development_checkout(self) -> bool:
        """A git clone is updated with git, never by swapping folders."""
        return (self.install_directory / ".git").exists()


@dataclass(frozen=True)
class PendingAction:
    action: str  # ACTION_INSTALL or ACTION_ROLLBACK
    version: str


@dataclass(frozen=True)
class ApplyResult:
    succeeded: bool
    message: str
    finished_at: str


# ---------------------------------------------------------------- small JSON helpers

def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def read_pending(layout: InstallLayout) -> PendingAction | None:
    content = _read_json(layout.pending_path)
    return PendingAction(**content) if content else None


def read_last_result(layout: InstallLayout) -> ApplyResult | None:
    content = _read_json(layout.last_result_path)
    return ApplyResult(**content) if content else None


def previous_version(layout: InstallLayout) -> Version | None:
    """The version a rollback would return to, if one is available."""
    content = _read_json(layout.previous_manifest_path)
    if not content or not layout.previous_directory.is_dir():
        return None
    return parse_version(content.get("version", ""))


def clear_pending(layout: InstallLayout) -> None:
    _remove(layout.pending_path)
    _remove(layout.staged_directory)


# ---------------------------------------------------------------- staging

def _safe_member_path(member_name: str) -> PurePosixPath | None:
    """The member's path without the zip's top-level folder, or None for the
    folder itself. Rejects absolute paths and '..' (a zip-slip attack)."""
    path = PurePosixPath(member_name)
    if path.is_absolute() or ".." in path.parts:
        raise UpdateError(f"Release archive contains an unsafe path: {member_name}")
    return PurePosixPath(*path.parts[1:]) if len(path.parts) > 1 else None


def stage_release(layout: InstallLayout, zip_path: Path, expected_version: Version) -> None:
    """Unpack a release zip into updates/staged and mark it pending.

    GitHub zips hold one top-level folder (e.g. ``sarlog-0.2.1/``); its
    contents become the staged release.
    """
    if layout.is_development_checkout():
        raise UpdateError("This copy is a git checkout; update it with git instead.")
    clear_pending(layout)
    unpack_directory = layout.updates_directory / "unpacking"
    _remove(unpack_directory)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            top_level_names = {PurePosixPath(name).parts[0] for name in archive.namelist() if name.strip("/")}
            if len(top_level_names) != 1:
                raise UpdateError("Release archive should contain exactly one top-level folder")
            for member in archive.infolist():
                relative_path = _safe_member_path(member.filename)
                if relative_path is None or relative_path.parts[0] in PROTECTED_NAMES:
                    continue
                target = unpack_directory.joinpath(*relative_path.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(member))
    except zipfile.BadZipFile as error:
        _remove(unpack_directory)
        raise UpdateError("The downloaded file is not a valid release archive") from error
    except UpdateError:
        _remove(unpack_directory)
        raise

    staged_version = read_installed_version(unpack_directory)
    if staged_version != expected_version:
        _remove(unpack_directory)
        raise UpdateError(f"Release archive is version {staged_version}, expected {expected_version}")
    unpack_directory.rename(layout.staged_directory)
    _write_json(layout.pending_path, asdict(PendingAction(ACTION_INSTALL, str(expected_version))))


def request_rollback(layout: InstallLayout) -> Version:
    version = previous_version(layout)
    if version is None:
        raise UpdateError("There is no previous version to go back to.")
    clear_pending(layout)
    _write_json(layout.pending_path, asdict(PendingAction(ACTION_ROLLBACK, str(version))))
    return version


# ---------------------------------------------------------------- applying

def pip_install_dependencies(install_directory: Path) -> None:
    """Re-install the package so new or changed dependencies are present."""
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-e", str(install_directory)],
        capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise UpdateError("Installing dependencies failed:\n" + completed.stderr[-2000:])


def _file_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _swap_in(layout: InstallLayout, incoming_directory: Path, outgoing_names: set[str],
             holding_directory: Path) -> tuple[list[str], list[str]]:
    """Move current entries to ``holding_directory`` and incoming ones into place.

    Returns (moved_out, moved_in). On any error, everything moved so far is
    put back before the error is re-raised.
    """
    root = layout.install_directory
    incoming_names = sorted(path.name for path in incoming_directory.iterdir()
                            if path.name not in PROTECTED_NAMES)
    outgoing = sorted((outgoing_names | set(incoming_names)) - PROTECTED_NAMES)
    holding_directory.mkdir(parents=True, exist_ok=True)
    moved_out, moved_in = [], []
    try:
        for name in outgoing:
            if (root / name).exists():
                (root / name).rename(holding_directory / name)
                moved_out.append(name)
        for name in incoming_names:
            (incoming_directory / name).rename(root / name)
            moved_in.append(name)
    except OSError:
        _undo_swap(root, incoming_directory, holding_directory, moved_out, moved_in)
        raise
    return moved_out, moved_in


def _undo_swap(root: Path, incoming_directory: Path, holding_directory: Path,
               moved_out: list[str], moved_in: list[str]) -> None:
    for name in reversed(moved_in):
        (root / name).rename(incoming_directory / name)
    for name in reversed(moved_out):
        (holding_directory / name).rename(root / name)


def apply_pending(
    layout: InstallLayout,
    install_dependencies: Callable[[Path], None] = pip_install_dependencies,
) -> ApplyResult | None:
    """Carry out a pending install or rollback. Returns None if nothing was pending.

    Must run while the app is stopped: the launcher calls it before starting
    the server.
    """
    pending = read_pending(layout)
    if pending is None:
        return None
    if layout.is_development_checkout():
        clear_pending(layout)
        return _finish(layout, False, "Skipped: this copy is a git checkout.")

    if pending.action == ACTION_INSTALL:
        incoming_directory = layout.staged_directory
    elif pending.action == ACTION_ROLLBACK:
        incoming_directory = layout.previous_directory
    else:
        clear_pending(layout)
        return _finish(layout, False, f"Unknown pending action {pending.action!r}; ignored.")
    if not incoming_directory.is_dir():
        clear_pending(layout)
        return _finish(layout, False, "The files for this update are missing; nothing was changed.")

    root = layout.install_directory
    current_version = read_installed_version(root)
    current_manifest = _read_json(layout.installed_manifest_path) or {}
    dependencies_changed = _file_bytes(incoming_directory / "pyproject.toml") != _file_bytes(root / "pyproject.toml")
    holding_directory = layout.updates_directory / "outgoing"
    _remove(holding_directory)

    try:
        moved_out, moved_in = _swap_in(layout, incoming_directory, set(current_manifest.get("entries", [])),
                                       holding_directory)
    except OSError as error:
        clear_pending(layout)
        return _finish(layout, False,
                       f"Could not replace files (is another copy of the app open?): {error}. "
                       f"Still on version {current_version}.")

    if dependencies_changed:
        try:
            install_dependencies(root)
        except Exception as error:  # noqa: BLE001 - any failure must roll back
            _undo_swap(root, incoming_directory, holding_directory, moved_out, moved_in)
            _try_reinstall(install_dependencies, root)
            clear_pending(layout)
            return _finish(layout, False, f"Update to {pending.version} failed and was undone: {error}")

    # The replaced code becomes the new "previous", so a rollback can undo
    # this step (and a rollback can itself be undone the same way).
    _remove(layout.previous_directory)
    holding_directory.rename(layout.previous_directory)
    _write_json(layout.previous_manifest_path, {"version": str(current_version), "entries": moved_out})
    _write_json(layout.installed_manifest_path, {"version": pending.version, "entries": moved_in})
    _remove(layout.staged_directory)
    _remove(layout.pending_path)
    verb = "Updated" if pending.action == ACTION_INSTALL else "Went back"
    return _finish(layout, True, f"{verb} from version {current_version} to {pending.version}.")


def _try_reinstall(install_dependencies: Callable[[Path], None], root: Path) -> None:
    try:
        install_dependencies(root)
    except Exception:  # noqa: BLE001 - best effort; the old environment usually still works
        pass


def _finish(layout: InstallLayout, succeeded: bool, message: str) -> ApplyResult:
    result = ApplyResult(succeeded, message, datetime.datetime.now().isoformat(timespec="seconds"))
    _write_json(layout.last_result_path, asdict(result))
    return result
