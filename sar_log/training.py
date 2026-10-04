"""Training: types of training, dated sessions, who attended, and summaries.

Questions this module answers:
* How many trainings has each active member done recently, and who has lapsed?
* For each training type, which active members are current, expired or never trained?
"""

from __future__ import annotations

import datetime
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from sar_log import audit
from sar_log.dates import add_months, parse_required_date
from sar_log.errors import NotFoundError, ValidationError
from sar_log.people import Person, list_people


@dataclass(frozen=True)
class TrainingType:
    id: int
    name: str
    description: str
    validity_months: int | None
    is_archived: bool


@dataclass(frozen=True)
class TrainingSession:
    id: int
    session_date: str
    training_type_id: int
    training_type_name: str
    title: str
    notes: str
    attendee_ids: tuple[int, ...]


# ---------------------------------------------------------------- types

def _row_to_type(row: sqlite3.Row) -> TrainingType:
    return TrainingType(row["id"], row["name"], row["description"], row["validity_months"],
                        bool(row["is_archived"]))


def list_training_types(connection: sqlite3.Connection, include_archived: bool = False) -> list[TrainingType]:
    query = "SELECT * FROM training_type"
    if not include_archived:
        query += " WHERE is_archived = 0"
    return [_row_to_type(row) for row in connection.execute(query + " ORDER BY name")]


def get_training_type(connection: sqlite3.Connection, training_type_id: int) -> TrainingType:
    row = connection.execute("SELECT * FROM training_type WHERE id = ?", (training_type_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"No training type with id {training_type_id}")
    return _row_to_type(row)


def _parse_validity(validity_months: int | str | None) -> int | None:
    if validity_months is None or str(validity_months).strip() == "":
        return None
    try:
        months = int(validity_months)
    except ValueError:
        raise ValidationError("Validity must be a whole number of months, or blank") from None
    if months <= 0:
        raise ValidationError("Validity must be a positive number of months, or blank")
    return months


def create_training_type(connection: sqlite3.Connection, name: str, description: str = "",
                         validity_months: int | str | None = None) -> TrainingType:
    name = name.strip()
    if not name:
        raise ValidationError("Training type name is required")
    if connection.execute("SELECT 1 FROM training_type WHERE name = ?", (name,)).fetchone():
        raise ValidationError(f"Training type '{name}' already exists")
    cursor = connection.execute(
        "INSERT INTO training_type (name, description, validity_months) VALUES (?, ?, ?)",
        (name, description.strip(), _parse_validity(validity_months)),
    )
    audit.record_change(connection, "training_type", cursor.lastrowid, "create", {"name": name})
    connection.commit()
    return get_training_type(connection, cursor.lastrowid)


def update_training_type(connection: sqlite3.Connection, training_type_id: int, name: str,
                         description: str, validity_months: int | str | None,
                         is_archived: bool = False) -> TrainingType:
    get_training_type(connection, training_type_id)
    name = name.strip()
    if not name:
        raise ValidationError("Training type name is required")
    clash = connection.execute("SELECT id FROM training_type WHERE name = ?", (name,)).fetchone()
    if clash and clash["id"] != training_type_id:
        raise ValidationError(f"Training type '{name}' already exists")
    connection.execute(
        """UPDATE training_type SET name = ?, description = ?, validity_months = ?, is_archived = ?
           WHERE id = ?""",
        (name, description.strip(), _parse_validity(validity_months), int(is_archived),
         training_type_id),
    )
    audit.record_change(connection, "training_type", training_type_id, "update", {"name": name})
    connection.commit()
    return get_training_type(connection, training_type_id)


# ---------------------------------------------------------------- sessions

def create_training_session(connection: sqlite3.Connection, session_date: str, training_type_id: int,
                            attendee_ids: list[int], title: str = "", notes: str = "") -> TrainingSession:
    get_training_type(connection, training_type_id)
    cursor = connection.execute(
        "INSERT INTO training_session (session_date, training_type_id, title, notes) VALUES (?, ?, ?, ?)",
        (parse_required_date(session_date, "Training date"), training_type_id, title.strip(), notes.strip()),
    )
    session_id = cursor.lastrowid
    _write_attendees(connection, session_id, attendee_ids)
    audit.record_change(connection, "training_session", session_id, "create",
                        {"date": session_date, "type": training_type_id, "attendees": attendee_ids})
    connection.commit()
    return get_training_session(connection, session_id)


def update_training_session(connection: sqlite3.Connection, session_id: int, session_date: str,
                            training_type_id: int, attendee_ids: list[int], title: str = "",
                            notes: str = "") -> TrainingSession:
    get_training_session(connection, session_id)
    get_training_type(connection, training_type_id)
    connection.execute(
        "UPDATE training_session SET session_date = ?, training_type_id = ?, title = ?, notes = ? WHERE id = ?",
        (parse_required_date(session_date, "Training date"), training_type_id, title.strip(),
         notes.strip(), session_id),
    )
    connection.execute("DELETE FROM training_attendance WHERE session_id = ?", (session_id,))
    _write_attendees(connection, session_id, attendee_ids)
    audit.record_change(connection, "training_session", session_id, "update",
                        {"date": session_date, "type": training_type_id, "attendees": attendee_ids})
    connection.commit()
    return get_training_session(connection, session_id)


def delete_training_session(connection: sqlite3.Connection, session_id: int) -> None:
    get_training_session(connection, session_id)
    connection.execute("DELETE FROM training_session WHERE id = ?", (session_id,))
    audit.record_change(connection, "training_session", session_id, "delete")
    connection.commit()


def _write_attendees(connection: sqlite3.Connection, session_id: int, attendee_ids: list[int]) -> None:
    connection.executemany(
        "INSERT OR IGNORE INTO training_attendance (session_id, person_id) VALUES (?, ?)",
        [(session_id, int(person_id)) for person_id in attendee_ids],
    )


def get_training_session(connection: sqlite3.Connection, session_id: int) -> TrainingSession:
    sessions = _load_sessions(connection, "WHERE training_session.id = ?", [session_id])
    if not sessions:
        raise NotFoundError(f"No training session with id {session_id}")
    return sessions[0]


def list_training_sessions(connection: sqlite3.Connection) -> list[TrainingSession]:
    return _load_sessions(connection, "", [])


def list_sessions_for_person(connection: sqlite3.Connection, person_id: int) -> list[TrainingSession]:
    return _load_sessions(
        connection,
        "WHERE training_session.id IN (SELECT session_id FROM training_attendance WHERE person_id = ?)",
        [person_id],
    )


def _load_sessions(connection: sqlite3.Connection, where_clause: str, parameters: list) -> list[TrainingSession]:
    rows = connection.execute(
        f"""SELECT training_session.*, training_type.name AS training_type_name
            FROM training_session JOIN training_type ON training_type.id = training_session.training_type_id
            {where_clause}
            ORDER BY training_session.session_date DESC, training_session.id DESC""",
        parameters,
    ).fetchall()
    attendees: dict[int, list[int]] = defaultdict(list)
    for attendance_row in connection.execute("SELECT session_id, person_id FROM training_attendance"):
        attendees[attendance_row["session_id"]].append(attendance_row["person_id"])
    return [
        TrainingSession(id=row["id"], session_date=row["session_date"],
                        training_type_id=row["training_type_id"],
                        training_type_name=row["training_type_name"], title=row["title"],
                        notes=row["notes"], attendee_ids=tuple(sorted(attendees[row["id"]])))
        for row in rows
    ]


# ---------------------------------------------------------------- summaries

def _attendance_dates(connection: sqlite3.Connection, as_of: datetime.date) -> dict[int, list[tuple[str, int]]]:
    """person id -> [(session date, training type id)] for sessions on or before as_of."""
    dates_by_person: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for row in connection.execute(
        """SELECT training_attendance.person_id, training_session.session_date,
                  training_session.training_type_id
           FROM training_attendance
           JOIN training_session ON training_session.id = training_attendance.session_id
           WHERE training_session.session_date <= ?""",
        (as_of.isoformat(),),
    ):
        dates_by_person[row["person_id"]].append((row["session_date"], row["training_type_id"]))
    return dates_by_person


@dataclass(frozen=True)
class MemberTrainingStatus:
    person: Person
    last_training_date: str | None
    sessions_in_period: int
    days_since_last_training: int | None
    is_lapsed: bool


def member_training_status(
    connection: sqlite3.Connection,
    as_of: datetime.date,
    period_months: int = 12,
    lapse_months: int = 12,
) -> list[MemberTrainingStatus]:
    """One row per active member, most overdue first.

    A member is lapsed when they have not trained within ``lapse_months`` of
    ``as_of``. Members who joined within that window are not counted as
    lapsed, since they have not yet had the chance.
    """
    dates_by_person = _attendance_dates(connection, as_of)
    period_start = add_months(as_of, -period_months).isoformat()
    lapse_cutoff = add_months(as_of, -lapse_months).isoformat()
    statuses = []
    for person in list_people(connection, active_on=as_of):
        session_dates = sorted(date for date, _ in dates_by_person.get(person.id, []))
        last_date = session_dates[-1] if session_dates else None
        joined_recently = person.joined_date is not None and person.joined_date > lapse_cutoff
        is_lapsed = not joined_recently and (last_date is None or last_date < lapse_cutoff)
        statuses.append(MemberTrainingStatus(
            person=person,
            last_training_date=last_date,
            sessions_in_period=sum(1 for date in session_dates if date > period_start),
            days_since_last_training=(
                (as_of - datetime.date.fromisoformat(last_date)).days if last_date else None),
            is_lapsed=is_lapsed,
        ))
    statuses.sort(key=lambda status: (not status.is_lapsed, status.last_training_date or "",
                                      status.person.full_name))
    return statuses


CURRENT, EXPIRED, NEVER = "current", "expired", "never"


@dataclass(frozen=True)
class QualificationCell:
    last_date: str | None
    status: str  # CURRENT, EXPIRED or NEVER


def qualification_status(last_date: str | None, validity_months: int | None,
                         as_of: datetime.date) -> str:
    if last_date is None:
        return NEVER
    if validity_months is None:
        return CURRENT
    expires_on = add_months(datetime.date.fromisoformat(last_date), validity_months)
    return CURRENT if expires_on > as_of else EXPIRED


@dataclass(frozen=True)
class QualificationMatrix:
    training_types: list[TrainingType]
    people: list[Person]
    # (person id, training type id) -> cell
    cells: dict[tuple[int, int], QualificationCell]


def qualification_matrix(connection: sqlite3.Connection, as_of: datetime.date) -> QualificationMatrix:
    training_types = list_training_types(connection)
    people = list_people(connection, active_on=as_of)
    dates_by_person = _attendance_dates(connection, as_of)
    cells = {}
    for person in people:
        last_date_by_type: dict[int, str] = {}
        for session_date, training_type_id in dates_by_person.get(person.id, []):
            if session_date > last_date_by_type.get(training_type_id, ""):
                last_date_by_type[training_type_id] = session_date
        for training_type in training_types:
            last_date = last_date_by_type.get(training_type.id)
            cells[(person.id, training_type.id)] = QualificationCell(
                last_date, qualification_status(last_date, training_type.validity_months, as_of))
    return QualificationMatrix(training_types, people, cells)


@dataclass(frozen=True)
class TrainingGap:
    training_type: TrainingType
    current_count: int
    expired_count: int
    never_count: int

    @property
    def active_member_count(self) -> int:
        return self.current_count + self.expired_count + self.never_count

    @property
    def current_fraction(self) -> float:
        return self.current_count / self.active_member_count if self.active_member_count else 0.0


def training_gaps(connection: sqlite3.Connection, as_of: datetime.date) -> list[TrainingGap]:
    """Per training type, how many active members are current. Biggest gaps first."""
    matrix = qualification_matrix(connection, as_of)
    gaps = []
    for training_type in matrix.training_types:
        statuses = [matrix.cells[(person.id, training_type.id)].status for person in matrix.people]
        gaps.append(TrainingGap(training_type, statuses.count(CURRENT), statuses.count(EXPIRED),
                                statuses.count(NEVER)))
    gaps.sort(key=lambda gap: (gap.current_fraction, gap.training_type.name))
    return gaps
