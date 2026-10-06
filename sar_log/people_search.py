"""Finding people by membership, organisation and training history.

Answers questions like "active members who have never done First Aid" or
"who has not trained at all since 1 March". Each criterion in PersonFilter
is optional; a blank filter returns everyone matching the membership choice.
"""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass

from sar_log.people import Person, list_people
from sar_log.training import (CURRENT, EXPIRED, NEVER, QualificationCell, attendance_by_person,
                              get_training_type, qualification_status)

# Membership choice -> label shown in the filter form.
MEMBERSHIP_CHOICES = {"active": "Active members", "left": "Left", "all": "Everyone"}

# Training status choice -> (label, statuses that match). Statuses are the
# qualification statuses from the training module.
TRAINING_STATUS_CHOICES: dict[str, tuple[str, frozenset[str]]] = {
    "done": ("has done it", frozenset({CURRENT, EXPIRED})),
    "current": ("is current", frozenset({CURRENT})),
    "not_current": ("is not current (expired or never)", frozenset({EXPIRED, NEVER})),
    "expired": ("has expired", frozenset({EXPIRED})),
    "never": ("has never done it", frozenset({NEVER})),
}


@dataclass(frozen=True)
class PersonFilter:
    membership: str = "active"
    organisation_id: int | None = None
    text: str = ""  # matched against name, SAR ID, email, phone and comments
    # When a training type is chosen, the status and date criteria below
    # apply to that type; otherwise the dates apply to any training.
    training_type_id: int | None = None
    training_status: str = ""
    trained_since: str | None = None  # last training on or after this date
    not_trained_since: str | None = None  # no training on or after this date (includes never)


@dataclass(frozen=True)
class PersonSummary:
    person: Person
    last_training_date: str | None  # most recent training of any type
    training_count: int
    job_count: int
    job_hours: float
    selected_training: QualificationCell | None  # only when the filter names a training type


def _job_totals_by_person(connection: sqlite3.Connection) -> dict[int, tuple[int, float]]:
    return {row["person_id"]: (row["job_count"], row["job_hours"]) for row in connection.execute(
        "SELECT person_id, COUNT(*) AS job_count, SUM(hours) AS job_hours FROM job_attendance GROUP BY person_id")}


def _matches_membership(person: Person, membership: str, as_of: datetime.date) -> bool:
    if membership == "active":
        return person.is_active_on(as_of)
    if membership == "left":
        return person.left_date is not None and person.left_date <= as_of.isoformat()
    return True


def _matches_text(person: Person, text: str) -> bool:
    needle = text.strip().casefold()
    searchable = [person.full_name, person.sar_id or "", person.email, person.phone, person.comments]
    return not needle or any(needle in value.casefold() for value in searchable)


def _matches_dates(last_date: str | None, person_filter: PersonFilter) -> bool:
    if person_filter.trained_since and (last_date is None or last_date < person_filter.trained_since):
        return False
    if person_filter.not_trained_since and last_date is not None and last_date >= person_filter.not_trained_since:
        return False
    return True


def search_people(connection: sqlite3.Connection, person_filter: PersonFilter,
                  as_of: datetime.date) -> list[PersonSummary]:
    """People matching every criterion of the filter, sorted by name."""
    attendance = attendance_by_person(connection, as_of)
    job_totals = _job_totals_by_person(connection)
    training_type = (get_training_type(connection, person_filter.training_type_id)
                     if person_filter.training_type_id is not None else None)
    status_choice = TRAINING_STATUS_CHOICES.get(person_filter.training_status)

    summaries = []
    for person in list_people(connection):
        if not _matches_membership(person, person_filter.membership, as_of):
            continue
        if person_filter.organisation_id is not None and person.organisation_id != person_filter.organisation_id:
            continue
        if not _matches_text(person, person_filter.text):
            continue
        sessions = attendance.get(person.id, [])
        last_date_any = max((session_date for session_date, _ in sessions), default=None)

        selected_training = None
        last_date_for_dates = last_date_any
        if training_type is not None:
            last_date_for_type = max((session_date for session_date, type_id in sessions
                                      if type_id == training_type.id), default=None)
            selected_training = QualificationCell(
                last_date_for_type,
                qualification_status(last_date_for_type, training_type.validity_months, as_of))
            last_date_for_dates = last_date_for_type
            if status_choice is not None and selected_training.status not in status_choice[1]:
                continue
        if not _matches_dates(last_date_for_dates, person_filter):
            continue

        job_count, job_hours = job_totals.get(person.id, (0, 0.0))
        summaries.append(PersonSummary(person, last_date_any, len(sessions), job_count, job_hours,
                                       selected_training))
    return summaries

