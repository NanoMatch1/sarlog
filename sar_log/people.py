"""People: volunteers and anyone else who attends jobs or training."""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass

from sar_log import audit
from sar_log.dates import parse_optional_date, whole_months_between
from sar_log.errors import NotFoundError, ValidationError


@dataclass(frozen=True)
class ServiceLength:
    """Time from joining to leaving (or to today), in whole years and months."""

    years: int
    months: int

    @classmethod
    def from_months(cls, total_months: int) -> "ServiceLength":
        years, months = divmod(total_months, 12)
        return cls(years, months)


@dataclass(frozen=True)
class Person:
    id: int
    sar_id: str | None
    full_name: str
    organisation_id: int | None
    organisation_name: str | None
    joined_date: str | None
    left_date: str | None
    email: str
    phone: str
    comments: str

    def is_active_on(self, as_of: datetime.date) -> bool:
        """Active means joined on or before the date and not yet left."""
        as_of_text = as_of.isoformat()
        if self.joined_date and self.joined_date > as_of_text:
            return False
        return self.left_date is None or self.left_date > as_of_text

    def service_length(self, as_of: datetime.date) -> ServiceLength | None:
        """Time since joined, stopping at the 'Left' date. None without a joined date."""
        if not self.joined_date:
            return None
        end = as_of
        if self.left_date:
            end = min(end, datetime.date.fromisoformat(self.left_date))
        return ServiceLength.from_months(
            whole_months_between(datetime.date.fromisoformat(self.joined_date), end))


@dataclass(frozen=True)
class PersonInput:
    """Everything a form or import supplies to create or update a person."""

    full_name: str
    sar_id: str = ""
    organisation_id: int | None = None
    joined_date: str = ""
    left_date: str = ""
    email: str = ""
    phone: str = ""
    comments: str = ""


_PERSON_QUERY = """
    SELECT person.*, organisation.name AS organisation_name
    FROM person LEFT JOIN organisation ON organisation.id = person.organisation_id
"""


def _row_to_person(row: sqlite3.Row) -> Person:
    return Person(
        id=row["id"], sar_id=row["sar_id"], full_name=row["full_name"],
        organisation_id=row["organisation_id"], organisation_name=row["organisation_name"],
        joined_date=row["joined_date"], left_date=row["left_date"],
        email=row["email"], phone=row["phone"], comments=row["comments"],
    )


def list_people(connection: sqlite3.Connection, active_on: datetime.date | None = None) -> list[Person]:
    people = [_row_to_person(row)
              for row in connection.execute(_PERSON_QUERY + " ORDER BY person.full_name")]
    if active_on is not None:
        people = [person for person in people if person.is_active_on(active_on)]
    return people


def get_person(connection: sqlite3.Connection, person_id: int) -> Person:
    row = connection.execute(_PERSON_QUERY + " WHERE person.id = ?", (person_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"No person with id {person_id}")
    return _row_to_person(row)


def _validated_values(connection: sqlite3.Connection, person_input: PersonInput,
                      person_id: int | None) -> dict:
    full_name = person_input.full_name.strip()
    if not full_name:
        raise ValidationError("Name is required")
    sar_id = person_input.sar_id.strip() or None
    if sar_id:
        clash = connection.execute("SELECT id FROM person WHERE sar_id = ?", (sar_id,)).fetchone()
        if clash and clash["id"] != person_id:
            raise ValidationError(f"SAR ID '{sar_id}' is already used by another person")
    joined_date = parse_optional_date(person_input.joined_date, "Joined")
    left_date = parse_optional_date(person_input.left_date, "Left")
    if joined_date and left_date and left_date < joined_date:
        raise ValidationError("'Left' date is before 'Joined' date")
    return {
        "full_name": full_name, "sar_id": sar_id,
        "organisation_id": person_input.organisation_id,
        "joined_date": joined_date, "left_date": left_date,
        "email": person_input.email.strip(), "phone": person_input.phone.strip(),
        "comments": person_input.comments.strip(),
    }


def create_person(connection: sqlite3.Connection, person_input: PersonInput) -> Person:
    values = _validated_values(connection, person_input, None)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    cursor = connection.execute(f"INSERT INTO person ({columns}) VALUES ({placeholders})",
                                tuple(values.values()))
    audit.record_change(connection, "person", cursor.lastrowid, "create",
                        {"full_name": values["full_name"]})
    connection.commit()
    return get_person(connection, cursor.lastrowid)


def update_person(connection: sqlite3.Connection, person_id: int, person_input: PersonInput) -> Person:
    get_person(connection, person_id)
    values = _validated_values(connection, person_input, person_id)
    assignments = ", ".join(f"{column} = ?" for column in values)
    connection.execute(f"UPDATE person SET {assignments} WHERE id = ?",
                       (*values.values(), person_id))
    audit.record_change(connection, "person", person_id, "update", values)
    connection.commit()
    return get_person(connection, person_id)


def delete_person(connection: sqlite3.Connection, person_id: int) -> None:
    """Delete someone with no job or training history. People with history
    should be given a 'Left' date instead, so their past hours stay counted."""
    person = get_person(connection, person_id)
    history_count = connection.execute(
        """SELECT (SELECT COUNT(*) FROM job_attendance WHERE person_id = ?)
                + (SELECT COUNT(*) FROM training_attendance WHERE person_id = ?)""",
        (person_id, person_id),
    ).fetchone()[0]
    if history_count:
        raise ValidationError(
            f"{person.full_name} has job or training history; set a 'Left' date instead of deleting"
        )
    connection.execute("DELETE FROM person WHERE id = ?", (person_id,))
    audit.record_change(connection, "person", person_id, "delete", {"full_name": person.full_name})
    connection.commit()
