"""Flask web interface. ``create_app`` is the only entry point."""

from __future__ import annotations

import os
from typing import Callable

from flask import Flask, abort, g, redirect, render_template, request, url_for

from sar_log.config import AppConfig, make_update_source
from sar_log.database import connect, open_database
from sar_log.errors import NotFoundError
from sar_log.updater.installer import InstallLayout
from sar_log.updater.sources import UpdateSource
from sar_log.web import (admin_views, fields_views, jobs_views, people_views, reports_views,
                         training_views, updates_views)

# Each views module exposes a ``blueprint``. This tuple is the one place a new
# page module is wired in.
VIEW_MODULES = (jobs_views, people_views, training_views, reports_views, fields_views, admin_views,
                updates_views)

LOCAL_HOST_NAMES = {"127.0.0.1", "localhost"}


def create_app(
    config: AppConfig,
    extra_allowed_hosts: tuple[str, ...] = (),
    update_source: UpdateSource | None = None,
    restart_callback: Callable[[], None] | None = None,
) -> Flask:
    app = Flask(__name__)
    app.config["SAR_LOG"] = config
    # Only used to sign flash messages; a new key each start is fine.
    app.secret_key = os.urandom(32)
    allowed_host_names = LOCAL_HOST_NAMES | set(extra_allowed_hosts)

    # Create (or migrate) the database up front so problems show at start-up.
    open_database(config.database_path).close()

    update_context = updates_views.UpdateContext(
        source=update_source or make_update_source(config),
        layout=InstallLayout(config.install_directory),
        restart=restart_callback or updates_views.default_restart(),
    )
    app.extensions[updates_views.EXTENSION_KEY] = update_context
    if config.check_for_updates_on_start and not update_context.layout.is_development_checkout():
        updates_views.start_background_check(update_context)

    @app.before_request
    def reject_foreign_requests():
        # Host check: defeats DNS-rebinding, where a web page on another site
        # tricks the browser into reading this local app.
        if request.host.rsplit(":", 1)[0] not in allowed_host_names:
            abort(403)
        # Origin check: defeats cross-site form posts that would change data.
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                abort(403)

    @app.before_request
    def open_connection():
        g.connection = connect(config.database_path)

    @app.teardown_request
    def close_connection(_error):
        connection = g.pop("connection", None)
        if connection is not None:
            connection.close()

    for module in VIEW_MODULES:
        app.register_blueprint(module.blueprint)

    @app.errorhandler(NotFoundError)
    def not_found(error):
        return render_template("not_found.html", message=str(error)), 404

    @app.route("/")
    def home():
        return redirect(url_for("jobs.list_jobs_page"))

    return app
