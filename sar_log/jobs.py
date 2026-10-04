"""Jobs (SAR operations), their field values, and who attended for how long."""

from __future__ import annotations

import datetime
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from sar_log import audit
from sar_log.dates import parse_optional_date, parse_required_date
from sar_log.errors import NotFoundError, ValidationError
from sar_log.fields import FieldDefinition, list_field_definitions
from sar_log.people import get_person


@dataclass(frozen=True)
class Job:
    id: int
    event_number: str
    start_date: str
    name: str
    notes: str
    field_values: dict[str, list[str]] = field(default_factory=dict)

    def values_for(self, field_key: str) -> list[str]:
        return self.field_values.get(field_key, [])


@dataclass(frozen=True)
class JobInput:
    """Everything a form or import supplies for a job.

    ``raw_field_values`` maps field key to the raw strings entered. Only keys
    present are written, so an update can touch a subset of fields.
    """

    event_number: str
    start_date: str
    name: str = ""
    notes: str = ""
    raw_field_values: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class AttendanceRecord:
    id: int
    job_id: int
    person_id: int
    person_name: str
    organisation_id: int | None
    organisation_name: str | None
    hours: float
    role: str


@dataclass(frozen=True)
class JobTotals:
    person_hours: float
    staff_count: int
    hours_by_organisation: dict[str, float]


UNASSIGNED_ORGANISATION = "(no organisation)"


# ---------------------------------------------------------------- validation

def validate_field_values(
    definitions: list[FieldDefinition],
    raw_field_values: dict[str, list[str]],
    require_all: bool,
) -> dict[str, list[str]]:
    """Validate raw input against the definitions; return values to store.

    With ``require_all`` (creating a job) every required field must be present.
    Otherwise only the supplied keys are checked.
    """
    definitions_by_key = {definition.key: definition for definition in definitions}
    unknown_keys = set(raw_field_values) - set(definitions_by_key)
    if unknown_keys:
        raise ValidationError(f"Unknown or archived fields: {', '.join(sorted(unknown_keys))}")
    errors, cleaned = [], {}
    for definition in definitions:
        if definition.key not in raw_field_values and not require_all:
            continue
        raw_values = raw_field_values.get(definition.key, [])
        try:
            cleaned[definition.key] = definition.field_type.to_storage(raw_values, definition.spec)
        except ValidationError as error:
            errors.append(str(error))
    if errors:
        raise ValidationError("; ".join(errors))
    return cleaned


def _validated_core(job_input: JobInput) -> dict:
    event_number = job_input.event_number.strip()
    if not event_number:
        raise ValidationError("Event number is required")
    return {
        "event_number": event_number,
        "start_date": parse_required_date(job_input.start_date, "Date"),
        "name": job_input.name.strip(),
        "notes": job_input.notes.strip(),
    }


def _check_event_number_unique(connection: sqlite3.Connection, event_number: str,
                               job_id: int | None) -> None:
    clash = connection.execute("SELECT id FROM job WHERE event_number = ?", (event_number,)).fetchone()
    if clash and clash["id"] != job_id:
        raise ValidationError(f"Event number '{event_number}' already exists")


def _write_field_values(connection: sqlite3.Connection, job_id: int,
                        cleaned_values: dict[str, list[str]]) -> None:
    for field_key, values in cleaned_values.items():
        connection.execute("DELETE FROM job_field_value WHERE job_id = ? AND field_key = ?",
                           (job_id, field_key))
        connection.executemany(
            "INSERT INTO job_field_value (job_id, field_key, value) VALUES (?, ?, ?)",
            [(job_id, field_key, value) for value in values],
        )


# ---------------------------------------------------------------- job CRUD

def create_job(connection: sqlite3.Connection, job_input: JobInput) -> Job:
    core = _validated_core(job_input)
    _check_event_number_unique(connection, core["event_number"], None)
    cleaned_values = validate_field_values(
        list_field_definitions(connection), job_input.raw_field_values, require_all=True)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    cursor = connection.execute(
        """INSERT INTO job (event_number, start_date, name, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (core["event_number"], core["start_date"], core["name"], core["notes"], now, now),
    )
    job_id = cursor.lastrowid
    _write_field_values(connection, job_id, cleaned_values)
    audit.record_change(connection, "job", job_id, "create", {**core, "fields": cleaned_values})
    connection.commit()
    return get_job(connection, job_id)


def update_job(connection: sqlite3.Connection, job_id: int, job_input: JobInput) -> Job:
    get_job(connection, job_id)
    core = _validated_core(job_input)
    _check_event_number_unique(connection, core["event_number"], job_id)
    cleaned_values = validate_field_values(
        list_field_definitions(connection), job_input.raw_field_values, require_all=False)
    connection.execute(
        """UPDATE job SET event_number = ?, start_date = ?, name = ?, notes = ?, updated_at = ?
           WHERE id = ?""",
        (core["event_number"], core["start_date"], core["name"], core["notes"],
         datetime.datetime.now().isoformat(timespec="seconds"), job_id),
    )
    _write_field_values(connection, job_id, cleaned_values)
    audit.record_change(connection, "job", job_id, "update", {**core, "fields": cleaned_values})
    connection.commit()
    return get_job(connection, job_id)


def delete_job(connection: sqlite3.Connection, job_id: int) -> None:
    job = get_job(connection, job_id)
    connection.execute("DELETE FROM job WHERE id = ?", (job_id,))
    audit.record_change(connection, "job", job_id, "delete", {"event_number": job.event_number})
    connection.commit()


def get_job(connection: sqlite3.Connection, job_id: int) -> Job:
    jobs = _load_jobs(connection, "WHERE job.id = ?", [job_id])
    if not jobs:
        raise NotFoundError(f"No job with id {job_id}")
    return jobs[0]


@dataclass(frozen=True)
class JobFilter:
    """Criteria for listing jobs. Blank criteria are ignored."""

    start_date: str | None = None
    end_date: str | None = None
    text: str = ""
    # field key -> value that must be stored for that field
    field_equals: dict[str, str] = field(default_factory=dict)


def list_jobs(connection: sqlite3.Connection, job_filter: JobFilter | None = None) -> list[Job]:
    job_filter = job_filter or JobFilter()
    conditions, parameters = [], []
    start_date = parse_optional_date(job_filter.start_date, "From")
    end_date = parse_optional_date(job_filter.end_date, "To")
    if start_date:
        conditions.append("job.start_date >= ?")
        parameters.append(start_date)
    if end_date:
        conditions.append("job.start_date <= ?")
        parameters.append(end_date)
    if job_filter.text.strip():
        pattern = f"%{job_filter.text.strip()}%"
        conditions.append(
            """(job.event_number LIKE ? OR job.name LIKE ? OR job.notes LIKE ?
                OR EXISTS (SELECT 1 FROM job_field_value AS searched
                           WHERE searched.job_id = job.id AND searched.value LIKE ?))""")
        parameters.extend([pattern] * 4)
    for field_key, value in job_filter.field_equals.items():
        conditions.append(
            """EXISTS (SELECT 1 FROM job_field_value AS filtered
                       WHERE filtered.job_id = job.id AND filtered.field_key = ?
                       AND filtered.value = ?)""")
        parameters.extend([field_key, value])
    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return _load_jobs(connection, where_clause, parameters)


def _load_jobs(connection: sqlite3.Connection, where_clause: str, parameters: list) -> list[Job]:
    job_rows = connection.execute(
        f"SELECT * FROM job {where_clause} ORDER BY job.start_date DESC, job.event_number DESC",
        parameters,
    ).fetchall()
    if not job_rows:
        return []
    job_ids = [row["id"] for row in job_rows]
    values_by_job: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    placeholders = ",".join("?" for _ in job_ids)
    for value_row in connection.execute(
        f"SELECT job_id, field_key, value FROM job_field_value WHERE job_id IN ({placeholders})",
        job_ids,
    ):
        values_by_job[value_row["job_id"]][value_row["field_key"]].append(value_row["value"])
    choice_positions = {
        definition.key: {choice: position for position, choice in enumerate(definition.choices)}
        for definition in list_field_definitions(connection, include_archived=True)
    }

    def in_choice_order(field_key: str, values: list[str]) -> list[str]:
        # The table's key order is alphabetical; show multi-choice values in
        # the order the field lists its choices instead.
        positions = choice_positions.get(field_key, {})
        return sorted(values, key=lambda value: (positions.get(value, len(positions)), value))

    return [
        Job(id=row["id"], event_number=row["event_number"], start_date=row["start_date"],
            name=row["name"], notes=row["notes"],
            field_values={key: in_choice_order(key, values)
                          for key, values in values_by_job[row["id"]].items()})
        for row in job_rows
    ]


# ---------------------------------------------------------------- attendance

def set_attendance(
    connection: sqlite3.Connection,
    job_id: int,
    person_id: int,
    hours: float | str,
    role: str = "",
    organisation_id: int | None = None,
    use_person_organisation: bool = True,
) -> None:
    """Record (or replace) one person's hours on a job.

    With ``use_person_organisation`` the person's current organisation is
    stored, which is what the form does; an import can pass an explicit one.
    """
    get_job(connection, job_id)
    person = get_person(connection, person_id)
    try:
        hours_value = float(hours)
    except (TypeError, ValueError):
        raise ValidationError(f"Hours must be a number, got {hours!r}") from None
    if hours_value < 0:
        raise ValidationError("Hours cannot be negative")
    if use_person_organisation:
        organisation_id = person.organisation_id
    connection.execute(
        """INSERT INTO job_attendance (job_id, person_id, organisation_id, hours, role)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (job_id, person_id)
           DO UPDATE SET hours = excluded.hours, role = excluded.role,
                         organisation_id = excluded.organisation_id""",
        (job_id, person_id, organisation_id, hours_value, role.strip()),
    )
    audit.record_change(connection, "job_attendance", f"{job_id}:{person_id}", "set",
                        {"hours": hours_value, "role": role, "organisation_id": organisation_id})
    connection.commit()


def remove_attendance(connection: sqlite3.Connection, attendance_id: int) -> None:
    row = connection.execute("SELECT * FROM job_attendance WHERE id = ?", (attendance_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"No attendance record {attendance_id}")
    connection.execute("DELETE FROM job_attendance WHERE id = ?", (attendance_id,))
    audit.record_change(connection, "job_attendance", f"{row['job_id']}:{row['person_id']}", "remove",
                        {"hours": row["hours"]})
    connection.commit()


def list_attendance_for_job(connection: sqlite3.Connection, job_id: int) -> list[AttendanceRecord]:
    return _load_attendance(connection, "WHERE job_attendance.job_id = ?", [job_id])


def list_attendance_for_person(connection: sqlite3.Connection, person_id: int) -> list[tuple[Job, AttendanceRecord]]:
    records = _load_attendance(connection, "WHERE job_attendance.person_id = ?", [person_id])
    return [(get_job(connection, record.job_id), record) for record in records]


def _load_attendance(connection: sqlite3.Connection, where_clause: str,
                     parameters: list) -> list[AttendanceRecord]:
    rows = connection.execute(
        f"""SELECT job_attendance.*, person.full_name AS person_name,
                   organisation.name AS organisation_name
            FROM job_attendance
            JOIN person ON person.id = job_attendance.person_id
            LEFT JOIN organisation ON organisation.id = job_attendance.organisation_id
            {where_clause}
            ORDER BY person.full_name""",
        parameters,
    )
    return [
        AttendanceRecord(id=row["id"], job_id=row["job_id"], person_id=row["person_id"],
                         person_name=row["person_name"], organisation_id=row["organisation_id"],
                         organisation_name=row["organisation_name"], hours=row["hours"],
                         role=row["role"])
        for row in rows
    ]


def job_totals(connection: sqlite3.Connection, job_id: int) -> JobTotals:
    return compute_totals(list_attendance_for_job(connection, job_id))


def compute_totals(attendance_records: list[AttendanceRecord]) -> JobTotals:
    hours_by_organisation: dict[str, float] = defaultdict(float)
    for record in attendance_records:
        hours_by_organisation[record.organisation_name or UNASSIGNED_ORGANISATION] += record.hours
    return JobTotals(
        person_hours=sum(record.hours for record in attendance_records),
        staff_count=len(attendance_records),
        hours_by_organisation=dict(sorted(hours_by_organisation.items())),
    )
