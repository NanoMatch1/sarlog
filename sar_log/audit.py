"""Append-only change log, so edits by any data-entry volunteer can be traced."""

from __future__ import annotations

import datetime
import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ChangeRecord:
    changed_at: str
    entity: str
    entity_id: str
    action: str
    detail: dict


def record_change(
    connection: sqlite3.Connection,
    entity: str,
    entity_id: object,
    action: str,
    detail: dict | None = None,
) -> None:
    connection.execute(
        """INSERT INTO change_log (changed_at, entity, entity_id, action, detail_json)
           VALUES (?, ?, ?, ?, ?)""",
        (
            datetime.datetime.now().isoformat(timespec="seconds"),
            entity,
            str(entity_id),
            action,
            json.dumps(detail or {}, default=str, sort_keys=True),
        ),
    )


def list_changes(
    connection: sqlite3.Connection,
    entity: str | None = None,
    entity_id: object | None = None,
    limit: int = 200,
) -> list[ChangeRecord]:
    query = "SELECT * FROM change_log"
    conditions, parameters = [], []
    if entity is not None:
        conditions.append("entity = ?")
        parameters.append(entity)
    if entity_id is not None:
        conditions.append("entity_id = ?")
        parameters.append(str(entity_id))
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id DESC LIMIT ?"
    parameters.append(limit)
    return [
        ChangeRecord(row["changed_at"], row["entity"], row["entity_id"], row["action"],
                     json.loads(row["detail_json"]))
        for row in connection.execute(query, parameters)
    ]
