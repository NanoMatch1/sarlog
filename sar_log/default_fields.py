"""Job field definitions created in a new database.

These mirror the columns of the original operations spreadsheet. They are only
a starting point: after creation every definition is edited from the
"Fields" page and lives in the database, which is the single source of truth.
Seeding uses INSERT OR IGNORE, so edits made in the app are never overwritten.

Spreadsheet columns not yet seeded because their meaning is unconfirmed:
W/S, U, B, K, U/K. Add them from the Fields page once confirmed.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DefaultField:
    key: str
    label: str
    value_type: str
    section: str
    description: str = ""
    choices: tuple[str, ...] = field(default_factory=tuple)
    is_required: bool = False


DEFAULT_FIELDS: tuple[DefaultField, ...] = (
    DefaultField("environment", "Environment", "choice", "Incident",
                 "Land or marine incident.", ("Land", "Marine"), is_required=True),
    DefaultField("district", "District", "choice", "Incident",
                 "District the job took place in (P / H / T columns).",
                 ("Palmerston North", "Horowhenua", "Tararua", "Other")),
    DefaultField("location", "Location", "text", "Incident"),
    DefaultField("circumstances", "Circumstances", "long_text", "Incident"),
    DefaultField("days", "Days", "decimal", "Incident", "Days spent on the job."),
    DefaultField("how_reported", "How reported", "text", "Incident"),
    DefaultField("incident_controller", "Incident controller", "text", "Incident"),
    DefaultField("lost_party_type", "Lost party type", "multi_choice", "Lost party",
                 "Select all that apply.",
                 ("Day walker", "Hunter", "Tramper", "Mountain runner", "Adventure sports",
                  "Despondent", "Mental health", "Child", "Dementia", "Other")),
    DefaultField("plb", "PLB carried", "boolean", "Lost party",
                 "Personal locator beacon carried by the lost party."),
    DefaultField("injuries", "Injuries", "long_text", "Outcome",
                 "Description of injuries."),
    DefaultField("injured", "Injured", "boolean", "Outcome", "Spreadsheet column 'Inj'."),
    DefaultField("death", "Death", "boolean", "Outcome"),
    DefaultField("body_recovery", "Body recovery", "boolean", "Outcome"),
    DefaultField("bodies", "Bodies", "integer", "Outcome", "Number of bodies recovered."),
    DefaultField("dvi", "DVI", "boolean", "Outcome", "Disaster victim identification involved."),
    DefaultField("logged_in_d4h", "Logged in D4H", "boolean", "Admin"),
    DefaultField("logged_with_landsar", "Logged with LandSAR", "boolean", "Admin"),
)


def seed_default_fields(connection: sqlite3.Connection) -> None:
    for sort_order, default in enumerate(DEFAULT_FIELDS):
        connection.execute(
            """INSERT OR IGNORE INTO field_definition
               (key, label, value_type, section, description, choices_json, is_required, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                default.key,
                default.label,
                default.value_type,
                default.section,
                default.description,
                json.dumps(list(default.choices)),
                int(default.is_required),
                sort_order * 10,
            ),
        )
