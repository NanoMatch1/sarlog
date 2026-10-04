"""Small helpers shared by the view modules."""

from __future__ import annotations

import datetime
import sqlite3

from flask import Response, current_app, g, request

from sar_log.config import AppConfig


def connection() -> sqlite3.Connection:
    return g.connection


def app_config() -> AppConfig:
    return current_app.config["SAR_LOG"]


def form_text(name: str) -> str:
    return request.form.get(name, "").strip()


def form_optional_int(name: str) -> int | None:
    value = request.form.get(name, "").strip()
    return int(value) if value else None


def form_int_list(name: str) -> list[int]:
    return [int(value) for value in request.form.getlist(name) if value.strip()]


def query_date(name: str) -> str:
    """A date from the query string, or '' when absent or malformed."""
    value = request.args.get(name, "").strip()
    try:
        return datetime.date.fromisoformat(value).isoformat() if value else ""
    except ValueError:
        return ""


def query_as_of_date() -> datetime.date:
    value = query_date("as_of")
    return datetime.date.fromisoformat(value) if value else datetime.date.today()


def csv_response(csv_text: str, filename: str) -> Response:
    # The BOM makes Excel read the file as UTF-8 (macrons in Māori names).
    return Response("﻿" + csv_text, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
