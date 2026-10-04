"""Organisations people belong to (own group, neighbouring groups, Police, ...)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from sar_log import audit
from sar_log.errors import NotFoundError, ValidationError


@dataclass(frozen=True)
class Organisation:
    id: int
    name: str
    notes: str


def list_organisations(connection: sqlite3.Connection) -> list[Organisation]:
    return [Organisation(row["id"], row["name"], row["notes"])
            for row in connection.execute("SELECT * FROM organisation ORDER BY name")]


def get_organisation(connection: sqlite3.Connection, organisation_id: int) -> Organisation:
    row = connection.execute("SELECT * FROM organisation WHERE id = ?", (organisation_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"No organisation with id {organisation_id}")
    return Organisation(row["id"], row["name"], row["notes"])


def find_organisation_by_name(connection: sqlite3.Connection, name: str) -> Organisation | None:
    row = connection.execute("SELECT * FROM organisation WHERE name = ?", (name.strip(),)).fetchone()
    return Organisation(row["id"], row["name"], row["notes"]) if row else None


def create_organisation(connection: sqlite3.Connection, name: str, notes: str = "") -> Organisation:
    name = name.strip()
    if not name:
        raise ValidationError("Organisation name is required")
    if find_organisation_by_name(connection, name):
        raise ValidationError(f"Organisation '{name}' already exists")
    cursor = connection.execute("INSERT INTO organisation (name, notes) VALUES (?, ?)",
                                (name, notes.strip()))
    audit.record_change(connection, "organisation", cursor.lastrowid, "create", {"name": name})
    connection.commit()
    return get_organisation(connection, cursor.lastrowid)


def update_organisation(connection: sqlite3.Connection, organisation_id: int, name: str,
                        notes: str = "") -> Organisation:
    get_organisation(connection, organisation_id)
    name = name.strip()
    if not name:
        raise ValidationError("Organisation name is required")
    clash = find_organisation_by_name(connection, name)
    if clash and clash.id != organisation_id:
        raise ValidationError(f"Organisation '{name}' already exists")
    connection.execute("UPDATE organisation SET name = ?, notes = ? WHERE id = ?",
                       (name, notes.strip(), organisation_id))
    audit.record_change(connection, "organisation", organisation_id, "update", {"name": name})
    connection.commit()
    return get_organisation(connection, organisation_id)
