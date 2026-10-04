"""The launcher started by run_sar_log.bat: apply pending updates, run the app, restart on request.

It runs the server as a child process so that after an update the new code is
imported fresh. The child exits with ``RESTART_EXIT_CODE`` when the user
clicks "Restart" on the updates page; any other exit ends the launcher.

Keep this module small and stable: once started, the launcher itself keeps
running the old code until the window is closed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

from sar_log.updater.installer import (InstallLayout, apply_pending, pip_install_dependencies,
                                      previous_version, request_rollback)
from sar_log.updater.versions import read_installed_version

RESTART_EXIT_CODE = 75
# The server exits with this when the database is newer than the code, which
# happens after going back to a version older than the one that last used it.
DATABASE_TOO_NEW_EXIT_CODE = 76
SUPERVISED_ENVIRONMENT_VARIABLE = "SAR_LOG_SUPERVISED"
HEALTH_PATH = "/updates/health"


def is_supervised() -> bool:
    return os.environ.get(SUPERVISED_ENVIRONMENT_VARIABLE) == "1"


def app_already_running(address: str) -> bool:
    """True if a SAR Log server already answers at this address."""
    try:
        with urllib.request.urlopen(address.rstrip("/") + HEALTH_PATH, timeout=2) as response:
            return json.loads(response.read()).get("app") == "sar_log"
    except (OSError, ValueError):
        return False


def run_launcher(
    install_directory: Path,
    serve_arguments: list[str],
    address: str,
    run_server: Callable[[list[str]], int] | None = None,
    install_dependencies: Callable[[Path], None] = pip_install_dependencies,
    open_browser: Callable[[str], object] = webbrowser.open,
) -> int:
    """Loop: apply any pending update, run the server, repeat if it asks to restart.

    ``serve_arguments`` are the command-line arguments for ``python -m sar_log``
    up to and including the ``serve`` command.
    """
    if app_already_running(address):
        print(f"SAR Log is already running; opening {address}")
        open_browser(address)
        return 0
    run_server = run_server or _run_server_subprocess
    layout = InstallLayout(install_directory)
    first_start = True
    while True:
        result = apply_pending(layout, install_dependencies=install_dependencies)
        if result is not None:
            print(("" if result.succeeded else "UPDATE PROBLEM: ") + result.message)
        arguments = list(serve_arguments) + ([] if first_start else ["--no-browser"])
        exit_code = run_server(arguments)
        if exit_code == DATABASE_TOO_NEW_EXIT_CODE and _newer_version_available_locally(layout):
            version = request_rollback(layout)
            print(f"Returning to version {version}, which can open this database...")
        elif exit_code != RESTART_EXIT_CODE:
            return exit_code
        else:
            print("Restarting SAR Log...")
        first_start = False


def _newer_version_available_locally(layout: InstallLayout) -> bool:
    """True when updates/previous holds a newer version than the one installed."""
    installed, previous = read_installed_version(layout.install_directory), previous_version(layout)
    return installed is not None and previous is not None and previous > installed


def _run_server_subprocess(arguments: list[str]) -> int:
    environment = {**os.environ, SUPERVISED_ENVIRONMENT_VARIABLE: "1"}
    try:
        return subprocess.call([sys.executable, "-m", "sar_log", *arguments], env=environment)
    except KeyboardInterrupt:
        return 0
