"""Change history and backups."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for

from sar_log import audit
from sar_log.database import backup_database
from sar_log.web.helpers import app_config, connection

blueprint = Blueprint("admin", __name__)


@blueprint.route("/changes")
def changes_page():
    return render_template("changes.html", changes=audit.list_changes(connection(), limit=300))


@blueprint.route("/backup", methods=["POST"])
def backup_now_page():
    config = app_config()
    backup_path = backup_database(config.database_path, config.backup_directory, config.backup_keep_count)
    flash(f"Backup saved: {backup_path}")
    return redirect(url_for("admin.changes_page"))
