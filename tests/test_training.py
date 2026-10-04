import datetime

import pytest

from sar_log import training
from sar_log.dates import add_months
from sar_log.errors import ValidationError


def test_add_months_clamps_to_month_end():
    assert add_months(datetime.date(2026, 1, 31), 1) == datetime.date(2026, 2, 28)
    assert add_months(datetime.date(2026, 3, 15), -12) == datetime.date(2025, 3, 15)
    assert add_months(datetime.date(2026, 11, 30), 3) == datetime.date(2027, 2, 28)


def test_training_type_validation(connection):
    training.create_training_type(connection, "First aid", validity_months="24")
    with pytest.raises(ValidationError):
        training.create_training_type(connection, "first aid")
    with pytest.raises(ValidationError):
        training.create_training_type(connection, "River", validity_months="0")


def test_session_attendees_round_trip_and_update(connection, make_person):
    alice, bob = make_person("Alice"), make_person("Bob")
    river = training.create_training_type(connection, "River safety")
    session = training.create_training_session(connection, "2026-01-10", river.id, [alice.id, bob.id])
    assert session.attendee_ids == (alice.id, bob.id)
    updated = training.update_training_session(connection, session.id, "2026-01-11", river.id, [bob.id])
    assert updated.attendee_ids == (bob.id,)
    assert [found.id for found in training.list_sessions_for_person(connection, alice.id)] == []


def test_member_status_counts_period_and_flags_lapsed(connection, make_person, as_of):
    river = training.create_training_type(connection, "River safety")
    regular = make_person("Regular", joined_date="2020-01-01")
    lapsed = make_person("Lapsed", joined_date="2020-01-01")
    newcomer = make_person("Newcomer", joined_date="2026-05-01")
    make_person("Departed", joined_date="2020-01-01", left_date="2025-01-01")
    training.create_training_session(connection, "2026-03-01", river.id, [regular.id])
    training.create_training_session(connection, "2025-09-01", river.id, [regular.id])
    training.create_training_session(connection, "2025-03-01", river.id, [lapsed.id])
    # A session after as_of must not count.
    training.create_training_session(connection, "2026-08-01", river.id, [lapsed.id])

    statuses = {status.person.full_name: status
                for status in training.member_training_status(connection, as_of, 12, 12)}
    assert set(statuses) == {"Regular", "Lapsed", "Newcomer"}
    assert statuses["Regular"].sessions_in_period == 2
    assert not statuses["Regular"].is_lapsed
    assert statuses["Lapsed"].is_lapsed
    assert statuses["Lapsed"].last_training_date == "2025-03-01"
    assert statuses["Lapsed"].days_since_last_training == 486
    assert not statuses["Newcomer"].is_lapsed  # joined within the lapse window
    # Lapsed members are listed first.
    assert training.member_training_status(connection, as_of)[0].person.full_name == "Lapsed"


def test_qualification_matrix_and_gaps(connection, make_person, as_of):
    first_aid = training.create_training_type(connection, "First aid", validity_months=24)
    navigation = training.create_training_type(connection, "Navigation")
    current, expired, never = make_person("Current"), make_person("Expired"), make_person("Never")
    training.create_training_session(connection, "2025-01-01", first_aid.id, [current.id])
    training.create_training_session(connection, "2024-01-01", first_aid.id, [expired.id])
    training.create_training_session(connection, "2015-01-01", navigation.id, [current.id, expired.id])

    matrix = training.qualification_matrix(connection, as_of)
    assert matrix.cells[(current.id, first_aid.id)].status == training.CURRENT
    assert matrix.cells[(expired.id, first_aid.id)].status == training.EXPIRED
    assert matrix.cells[(never.id, first_aid.id)].status == training.NEVER
    assert matrix.cells[(expired.id, navigation.id)].status == training.CURRENT  # no expiry

    gaps = {gap.training_type.name: gap for gap in training.training_gaps(connection, as_of)}
    assert (gaps["First aid"].current_count, gaps["First aid"].expired_count, gaps["First aid"].never_count) == (1, 1, 1)
    assert gaps["Navigation"].current_count == 2
    assert training.training_gaps(connection, as_of)[0].training_type.name == "First aid"  # biggest gap first


def test_qualification_expires_exactly_at_validity_end():
    as_of = datetime.date(2026, 6, 30)
    assert training.qualification_status("2024-07-01", 24, as_of) == training.CURRENT
    assert training.qualification_status("2024-06-30", 24, as_of) == training.EXPIRED
