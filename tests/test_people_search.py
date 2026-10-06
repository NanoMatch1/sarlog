import datetime

import pytest

from sar_log import jobs, organisations, training
from sar_log.dates import whole_months_between
from sar_log.jobs import JobInput
from sar_log.people import ServiceLength
from sar_log.people_search import PersonFilter, search_people


@pytest.mark.parametrize("start, end, months", [
    ("2026-01-15", "2026-02-14", 0),
    ("2026-01-31", "2026-02-28", 1),
    ("2026-01-15", "2026-01-14", 0),
    ("2023-02-10", "2026-06-10", 40),
    ("2023-02-10", "2026-06-09", 39),
])
def test_whole_months_between(start, end, months):
    assert whole_months_between(datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)) == months


def test_service_length_stops_at_left_date(make_person, as_of):
    assert make_person("Current", joined_date="2023-02-10").service_length(as_of) == ServiceLength(3, 4)
    assert make_person("Gone", joined_date="2020-01-01", left_date="2021-07-15").service_length(as_of) \
        == ServiceLength(1, 6)
    assert make_person("Unknown").service_length(as_of) is None


@pytest.fixture
def roster(connection, make_person):
    """Four people with a mix of organisations, membership and training history."""
    home = organisations.create_organisation(connection, "Home Group")
    first_aid = training.create_training_type(connection, "First aid", validity_months=24)
    river = training.create_training_type(connection, "River safety")
    people = {
        "Ana": make_person("Ana", organisation_id=home.id, comments="radio operator"),
        "Ben": make_person("Ben", organisation_id=home.id),
        "Cat": make_person("Cat"),
        "Dan": make_person("Dan", left_date="2025-01-01"),
    }
    training.create_training_session(connection, "2026-03-01", first_aid.id, [people["Ana"].id])
    training.create_training_session(connection, "2023-03-01", first_aid.id, [people["Ben"].id])
    training.create_training_session(connection, "2026-05-01", river.id, [people["Ben"].id])
    job = jobs.create_job(connection, JobInput("E1", "2026-01-01", raw_field_values={"environment": ["Land"]}))
    jobs.set_attendance(connection, job.id, people["Ana"].id, 5)
    return {"home": home, "first_aid": first_aid, "river": river, **people}


def names(connection, as_of, **criteria):
    return [summary.person.full_name for summary in search_people(connection, PersonFilter(**criteria), as_of)]


def test_membership_and_organisation_and_text(connection, roster, as_of):
    assert names(connection, as_of) == ["Ana", "Ben", "Cat"]
    assert names(connection, as_of, membership="left") == ["Dan"]
    assert names(connection, as_of, membership="all") == ["Ana", "Ben", "Cat", "Dan"]
    assert names(connection, as_of, organisation_id=roster["home"].id) == ["Ana", "Ben"]
    assert names(connection, as_of, text="RADIO") == ["Ana"]


def test_training_status_for_a_chosen_type(connection, roster, as_of):
    first_aid_id = roster["first_aid"].id
    assert names(connection, as_of, training_type_id=first_aid_id, training_status="current") == ["Ana"]
    assert names(connection, as_of, training_type_id=first_aid_id, training_status="expired") == ["Ben"]
    assert names(connection, as_of, training_type_id=first_aid_id, training_status="never") == ["Cat"]
    assert names(connection, as_of, training_type_id=first_aid_id, training_status="not_current") == ["Ben", "Cat"]
    assert names(connection, as_of, training_type_id=first_aid_id, training_status="done") == ["Ana", "Ben"]


def test_dates_apply_to_any_training_or_to_the_chosen_type(connection, roster, as_of):
    assert names(connection, as_of, trained_since="2026-04-01") == ["Ben"]
    assert names(connection, as_of, not_trained_since="2026-04-01") == ["Ana", "Cat"]
    # Ben did river safety recently, but no first aid since 2023.
    assert names(connection, as_of, training_type_id=roster["first_aid"].id,
                 not_trained_since="2025-01-01") == ["Ben", "Cat"]


def test_summary_carries_totals(connection, roster, as_of):
    summaries = {summary.person.full_name: summary for summary in search_people(
        connection, PersonFilter(training_type_id=roster["first_aid"].id), as_of)}
    assert summaries["Ana"].job_count == 1 and summaries["Ana"].job_hours == 5
    assert summaries["Ben"].training_count == 2 and summaries["Ben"].last_training_date == "2026-05-01"
    assert summaries["Ben"].selected_training.last_date == "2023-03-01"
    assert summaries["Cat"].selected_training.status == "never"
