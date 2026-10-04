"""The Updates page: check for, install, and undo updates."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Callable

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

import sar_log
from sar_log.launcher import RESTART_EXIT_CODE, is_supervised
from sar_log.updater import installer
from sar_log.updater.changelog import notes_newer_than
from sar_log.updater.sources import UpdateSource, UpdateSourceError, find_release, latest_release
from sar_log.updater.versions import Version, parse_version

blueprint = Blueprint("updates", __name__)

EXTENSION_KEY = "sar_log_updates"


@dataclass
class UpdateContext:
    """Everything the updates pages need, injected by create_app."""

    source: UpdateSource
    layout: installer.InstallLayout
    # Called to restart the app after an update; None when not started by the launcher.
    restart: Callable[[], None] | None
    # Filled in by the background check at start-up.
    newest_available: Version | None = None
    background_check_error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)


def running_version() -> Version:
    return parse_version(sar_log.__version__)


def exit_for_restart() -> None:
    """Exit shortly after the current response is sent; the launcher restarts us."""
    threading.Timer(0.5, os._exit, [RESTART_EXIT_CODE]).start()


def default_restart() -> Callable[[], None] | None:
    return exit_for_restart if is_supervised() else None


def start_background_check(context: UpdateContext) -> None:
    def check() -> None:
        try:
            release = latest_release(context.source)
            with context.lock:
                context.newest_available = release.version if release else None
        except UpdateSourceError as error:
            context.background_check_error = str(error)

    threading.Thread(target=check, name="update-check", daemon=True).start()


def update_context() -> UpdateContext:
    return current_app.extensions[EXTENSION_KEY]


@blueprint.app_context_processor
def update_badge():
    """Lets every page show the version and an 'update available' badge."""
    context = current_app.extensions.get(EXTENSION_KEY)
    newest = context.newest_available if context else None
    return {"app_version": sar_log.__version__,
            "update_available": newest is not None and newest > running_version()}


@blueprint.route("/updates")
def updates_page():
    context = update_context()
    layout = context.layout
    check_error, newer_notes, latest = "", None, None
    if request.args.get("check"):
        try:
            release = latest_release(context.source)
            newer_notes = []
            if release is not None:
                with context.lock:
                    context.newest_available = release.version
                if release.version > running_version():
                    latest = release.version
                    newer_notes = notes_newer_than(context.source.changelog_text(release), running_version())
        except UpdateSourceError as error:
            check_error = str(error)
    return render_template(
        "updates.html",
        current_version=running_version(),
        source_description=context.source.description,
        is_development_checkout=layout.is_development_checkout(),
        can_restart=context.restart is not None,
        pending=installer.read_pending(layout),
        last_result=installer.read_last_result(layout),
        previous_version=installer.previous_version(layout),
        checked=bool(request.args.get("check")),
        check_error=check_error,
        latest=latest,
        newer_notes=newer_notes,
    )


@blueprint.route("/updates/install", methods=["POST"])
def install_update_page():
    context = update_context()
    version = parse_version(request.form.get("version", ""))
    try:
        if version is None:
            raise installer.UpdateError("No version was chosen.")
        release = find_release(context.source, version)
        zip_path = context.source.download(release, context.layout.downloads_directory / f"{version.tag}.zip")
        installer.stage_release(context.layout, zip_path, version)
        zip_path.unlink(missing_ok=True)
    except (UpdateSourceError, installer.UpdateError) as error:
        flash(f"Update not installed: {error}")
        return redirect(url_for("updates.updates_page"))
    flash(f"Version {version} is downloaded and ready. Restart SAR Log to finish.")
    return redirect(url_for("updates.updates_page"))


@blueprint.route("/updates/rollback", methods=["POST"])
def rollback_page():
    try:
        version = installer.request_rollback(update_context().layout)
    except installer.UpdateError as error:
        flash(str(error))
        return redirect(url_for("updates.updates_page"))
    flash(f"Ready to go back to version {version}. Restart SAR Log to finish.")
    return redirect(url_for("updates.updates_page"))


@blueprint.route("/updates/cancel", methods=["POST"])
def cancel_page():
    installer.clear_pending(update_context().layout)
    flash("Pending change cancelled.")
    return redirect(url_for("updates.updates_page"))


@blueprint.route("/updates/restart", methods=["POST"])
def restart_page():
    context = update_context()
    if context.restart is None:
        flash("Close the SAR Log window and start it again to finish.")
        return redirect(url_for("updates.updates_page"))
    context.restart()
    return render_template("restarting.html")


@blueprint.route("/updates/health")
def health():
    return jsonify(app="sar_log", version=sar_log.__version__)
