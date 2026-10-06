"""Feedback from the people using the app: problems, ideas and questions.

Messages are stored in the local database like everything else. Nothing is
sent anywhere automatically; the Feedback page offers the open messages as
text to copy (into an email or message) or as a CSV download.
"""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass

from sar_log import audit
from sar_log.errors import NotFoundError, ValidationError

# kind -> label shown to the user. Adding a kind is one entry here.
FEEDBACK_KINDS = {
    "problem": "Something isn't working",
    "idea": "Idea or feature request",
    "question": "Question",
}


@dataclass(frozen=True)
class Feedback:
    id: int
    created_at: str
    kind: str
    message: str
    page: str
    app_version: str
    is_resolved: bool
    resolution: str

    @property
    def kind_label(self) -> str:
        return FEEDBACK_KINDS.get(self.kind, self.kind)


def _row_to_feedback(row: sqlite3.Row) -> Feedback:
    return Feedback(row["id"], row["created_at"], row["kind"], row["message"], row["page"],
                    row["app_version"], bool(row["is_resolved"]), row["resolution"])


def create_feedback(connection: sqlite3.Connection, kind: str, message: str, page: str = "",
                    app_version: str = "", created_at: datetime.datetime | None = None) -> Feedback:
    if kind not in FEEDBACK_KINDS:
        raise ValidationError(f"Choose what kind of feedback this is ({', '.join(FEEDBACK_KINDS.values())})")
    message = message.strip()
    if not message:
        raise ValidationError("Write a message before sending feedback")
    stamp = (created_at or datetime.datetime.now()).isoformat(timespec="minutes")
    cursor = connection.execute(
        "INSERT INTO feedback (created_at, kind, message, page, app_version) VALUES (?, ?, ?, ?, ?)",
        (stamp, kind, message, page.strip(), app_version))
    audit.record_change(connection, "feedback", cursor.lastrowid, "create", {"kind": kind})
    connection.commit()
    return get_feedback(connection, cursor.lastrowid)


def get_feedback(connection: sqlite3.Connection, feedback_id: int) -> Feedback:
    row = connection.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"No feedback with id {feedback_id}")
    return _row_to_feedback(row)


def list_feedback(connection: sqlite3.Connection, include_resolved: bool = True) -> list[Feedback]:
    """Newest first."""
    query = "SELECT * FROM feedback"
    if not include_resolved:
        query += " WHERE is_resolved = 0"
    return [_row_to_feedback(row) for row in connection.execute(query + " ORDER BY created_at DESC, id DESC")]


def set_feedback_resolved(connection: sqlite3.Connection, feedback_id: int, is_resolved: bool,
                          resolution: str = "") -> Feedback:
    get_feedback(connection, feedback_id)
    connection.execute("UPDATE feedback SET is_resolved = ?, resolution = ? WHERE id = ?",
                       (int(is_resolved), resolution.strip(), feedback_id))
    audit.record_change(connection, "feedback", feedback_id, "resolve" if is_resolved else "reopen",
                        {"resolution": resolution.strip()})
    connection.commit()
    return get_feedback(connection, feedback_id)


def feedback_as_text(items: list[Feedback]) -> str:
    """Plain text suitable for pasting into an email, oldest first."""
    blocks = []
    for item in sorted(items, key=lambda item: (item.created_at, item.id)):
        heading = f"#{item.id} · {item.created_at.replace('T', ' ')} · {item.kind_label}"
        context = f"(page {item.page or 'unknown'}, version {item.app_version or 'unknown'})"
        blocks.append(f"{heading}\n{item.message}\n{context}")
    return "\n\n".join(blocks)
