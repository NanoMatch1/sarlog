import datetime

import pytest

from sar_log import jobs, organisations, people
from sar_log.errors import ValidationError
from sar_log.jobs import JobInput
from sar_log.people import PersonInput


def test_active_status_respects_joined_and_left_dates(make_person):
    person = make_person("Alice", joined_date="2025-01-01", left_date="2026-01-01")
    assert not person.is_active_on(datetime.date(2024, 12, 31))
    assert person.is_active_on(datetime.date(2025, 6, 1))
    assert not person.is_active_on(datetime.date(2026, 1, 1))


def test_list_people_active_filter(connection, make_person):
    make_person("Alice")
    make_person("Bob", left_date="2026-01-01")
    names = [person.full_name for person in people.list_people(connection, active_on=datetime.date(2026, 6, 1))]
    assert names == ["Alice"]


def test_validation(connection, make_person):
    with pytest.raises(ValidationError, match="Name is required"):
        make_person("  ")
    with pytest.raises(ValidationError, match="before"):
        make_person("Alice", joined_date="2026-01-01", left_date="2025-01-01")
    make_person("Bob", sar_id="S1")
    with pytest.raises(ValidationError, match="already used"):
        make_person("Carol", sar_id="S1")


def test_update_person_keeps_own_sar_id(connection, make_person, home_organisation):
    person = make_person("Alice", sar_id="S1")
    updated = people.update_person(connection, person.id,
                                   PersonInput("Alice Smith", sar_id="S1", organisation_id=home_organisation.id))
    assert updated.full_name == "Alice Smith"
    assert updated.organisation_name == "Home Group"


def test_delete_only_without_history(connection, make_person):
    alice = make_person("Alice")
    bob = make_person("Bob")
    job = jobs.create_job(connection, JobInput("E1", "2026-01-01", raw_field_values={"environment": ["Land"]}))
    jobs.set_attendance(connection, job.id, alice.id, 3)
    with pytest.raises(ValidationError, match="Left"):
        people.delete_person(connection, alice.id)
    people.delete_person(connection, bob.id)
    assert [person.full_name for person in people.list_people(connection)] == ["Alice"]


def test_organisation_names_are_unique_ignoring_case(connection):
    organisations.create_organisation(connection, "Police")
    with pytest.raises(ValidationError):
        organisations.create_organisation(connection, "police")
