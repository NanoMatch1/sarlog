"""Job field definitions: the user-editable list of details recorded per job."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from sar_log import audit
from sar_log.errors import NotFoundError, ValidationError
from sar_log.field_types import FieldSpec, FieldType, get_field_type


@dataclass(frozen=True)
class FieldDefinition:
    key: str
    label: str
    value_type: str
    section: str
    description: str
    choices: tuple[str, ...]
    is_required: bool
    is_archived: bool
    sort_order: int

    @property
    def field_type(self) -> FieldType:
        return get_field_type(self.value_type)

    @property
    def spec(self) -> FieldSpec:
        return FieldSpec(label=self.label, choices=self.choices, is_required=self.is_required)


def _row_to_definition(row: sqlite3.Row) -> FieldDefinition:
    return FieldDefinition(
        key=row["key"],
        label=row["label"],
        value_type=row["value_type"],
        section=row["section"],
        description=row["description"],
        choices=tuple(json.loads(row["choices_json"])),
        is_required=bool(row["is_required"]),
        is_archived=bool(row["is_archived"]),
        sort_order=row["sort_order"],
    )


def list_field_definitions(
    connection: sqlite3.Connection, include_archived: bool = False
) -> list[FieldDefinition]:
    query = "SELECT * FROM field_definition"
    if not include_archived:
        query += " WHERE is_archived = 0"
    query += " ORDER BY sort_order, label"
    return [_row_to_definition(row) for row in connection.execute(query)]


def get_field_definition(connection: sqlite3.Connection, key: str) -> FieldDefinition:
    row = connection.execute("SELECT * FROM field_definition WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise NotFoundError(f"No field with key {key!r}")
    return _row_to_definition(row)


def parse_choices_text(choices_text: str) -> tuple[str, ...]:
    """Turn one-choice-per-line text into a tuple, dropping blanks and duplicates."""
    seen: dict[str, str] = {}
    for line in choices_text.splitlines():
        choice = line.strip()
        if choice and choice.casefold() not in seen:
            seen[choice.casefold()] = choice
    return tuple(seen.values())


def make_field_key(label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if not key:
        raise ValidationError("A field needs a label containing letters or numbers")
    return key


def create_field_definition(
    connection: sqlite3.Connection,
    label: str,
    value_type: str,
    section: str = "Details",
    description: str = "",
    choices: tuple[str, ...] = (),
    is_required: bool = False,
) -> FieldDefinition:
    label = label.strip()
    field_type = get_field_type(value_type)
    _check_choices(field_type, choices)
    base_key = make_field_key(label)
    key, suffix = base_key, 2
    while connection.execute("SELECT 1 FROM field_definition WHERE key = ?", (key,)).fetchone():
        key, suffix = f"{base_key}_{suffix}", suffix + 1
    next_sort_order = connection.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 10 FROM field_definition"
    ).fetchone()[0]
    connection.execute(
        """INSERT INTO field_definition
           (key, label, value_type, section, description, choices_json, is_required, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (key, label, value_type, section.strip() or "Details", description.strip(),
         json.dumps(list(choices)), int(is_required), next_sort_order),
    )
    audit.record_change(connection, "field_definition", key, "create",
                        {"label": label, "value_type": value_type, "choices": list(choices)})
    connection.commit()
    return get_field_definition(connection, key)


def update_field_definition(
    connection: sqlite3.Connection,
    key: str,
    label: str,
    section: str,
    description: str,
    choices: tuple[str, ...],
    is_required: bool,
    sort_order: int,
) -> FieldDefinition:
    """Update a definition. The value type cannot change once created, because
    stored values were validated against it."""
    existing = get_field_definition(connection, key)
    _check_choices(existing.field_type, choices)
    if existing.field_type.uses_choices:
        removed_choices = set(existing.choices) - set(choices)
        in_use = _choices_in_use(connection, key, removed_choices)
        if in_use:
            raise ValidationError(
                f"Cannot remove choices still used by jobs: {', '.join(sorted(in_use))}. "
                "Rename them instead, or change those jobs first."
            )
    connection.execute(
        """UPDATE field_definition
           SET label = ?, section = ?, description = ?, choices_json = ?, is_required = ?, sort_order = ?
           WHERE key = ?""",
        (label.strip(), section.strip() or "Details", description.strip(),
         json.dumps(list(choices)), int(is_required), sort_order, key),
    )
    audit.record_change(connection, "field_definition", key, "update",
                        {"label": label, "choices": list(choices), "is_required": is_required})
    connection.commit()
    return get_field_definition(connection, key)


def rename_choice(connection: sqlite3.Connection, key: str, old_choice: str, new_choice: str) -> None:
    """Rename a choice everywhere: in the definition and in every stored value."""
    definition = get_field_definition(connection, key)
    new_choice = new_choice.strip()
    if old_choice not in definition.choices:
        raise ValidationError(f"'{old_choice}' is not a choice of '{definition.label}'")
    if not new_choice:
        raise ValidationError("The new choice name cannot be blank")
    if any(choice.casefold() == new_choice.casefold() for choice in definition.choices
           if choice != old_choice):
        raise ValidationError(f"'{new_choice}' is already a choice of '{definition.label}'")
    new_choices = tuple(new_choice if choice == old_choice else choice for choice in definition.choices)
    connection.execute("UPDATE field_definition SET choices_json = ? WHERE key = ?",
                       (json.dumps(list(new_choices)), key))
    connection.execute("UPDATE job_field_value SET value = ? WHERE field_key = ? AND value = ?",
                       (new_choice, key, old_choice))
    audit.record_change(connection, "field_definition", key, "rename_choice",
                        {"from": old_choice, "to": new_choice})
    connection.commit()


def set_field_archived(connection: sqlite3.Connection, key: str, is_archived: bool) -> None:
    """Archived fields disappear from forms but keep their stored values."""
    get_field_definition(connection, key)
    connection.execute("UPDATE field_definition SET is_archived = ? WHERE key = ?",
                       (int(is_archived), key))
    audit.record_change(connection, "field_definition", key,
                        "archive" if is_archived else "restore")
    connection.commit()


def count_jobs_using_field(connection: sqlite3.Connection, key: str) -> int:
    return connection.execute(
        "SELECT COUNT(DISTINCT job_id) FROM job_field_value WHERE field_key = ?", (key,)
    ).fetchone()[0]


def _check_choices(field_type: FieldType, choices: tuple[str, ...]) -> None:
    if field_type.uses_choices and not choices:
        raise ValidationError("A list field needs at least one choice")
    if not field_type.uses_choices and choices:
        raise ValidationError("Only list fields can have choices")


def _choices_in_use(connection: sqlite3.Connection, key: str, choices: set[str]) -> set[str]:
    if not choices:
        return set()
    placeholders = ",".join("?" for _ in choices)
    rows = connection.execute(
        f"SELECT DISTINCT value FROM job_field_value WHERE field_key = ? AND value IN ({placeholders})",
        (key, *choices),
    )
    return {row["value"] for row in rows}
