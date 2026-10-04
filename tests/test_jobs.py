import pytest

from sar_log import fields, jobs, organisations
from sar_log.errors import NotFoundError, ValidationError
from sar_log.jobs import JobFilter, JobInput


def land_job(event_number="E1", start_date="2026-03-01", **raw_field_values):
    return JobInput(event_number, start_date, name="Test",
                    raw_field_values={"environment": ["Land"], **raw_field_values})


def test_create_and_read_back_job_with_fields(connection):
    job = jobs.create_job(connection, land_job(lost_party_type=["Tramper", "Child"], plb=["yes"]))
    loaded = jobs.get_job(connection, job.id)
    assert loaded.event_number == "E1"
    assert loaded.values_for("lost_party_type") == ["Tramper", "Child"]
    assert loaded.values_for("plb") == ["yes"]
    assert loaded.values_for("district") == []


def test_required_field_missing_on_create_is_rejected(connection):
    with pytest.raises(ValidationError, match="'Environment' is required"):
        jobs.create_job(connection, JobInput("E1", "2026-03-01"))


def test_all_field_errors_are_reported_together(connection):
    with pytest.raises(ValidationError) as error:
        jobs.create_job(connection, land_job(bodies=["two"], plb=["perhaps"]))
    assert "Bodies" in str(error.value) and "PLB" in str(error.value)


def test_duplicate_event_number_is_rejected(connection):
    jobs.create_job(connection, land_job())
    with pytest.raises(ValidationError, match="already exists"):
        jobs.create_job(connection, land_job())


def test_unknown_field_key_is_rejected(connection):
    with pytest.raises(ValidationError, match="Unknown"):
        jobs.create_job(connection, land_job(made_up=["x"]))


def test_update_only_touches_supplied_fields(connection):
    job = jobs.create_job(connection, land_job(location=["Ridge"], district=["Tararua"]))
    jobs.update_job(connection, job.id, JobInput("E1", "2026-03-01", raw_field_values={"location": ["Valley"]}))
    loaded = jobs.get_job(connection, job.id)
    assert loaded.values_for("location") == ["Valley"]
    assert loaded.values_for("district") == ["Tararua"]


def test_update_with_blank_clears_value(connection):
    job = jobs.create_job(connection, land_job(location=["Ridge"]))
    jobs.update_job(connection, job.id, JobInput("E1", "2026-03-01", raw_field_values={"location": [""]}))
    assert jobs.get_job(connection, job.id).values_for("location") == []


def test_new_field_is_immediately_usable_on_jobs(connection):
    fields.create_field_definition(connection, "Cause of loss", "choice", choices=("Weather", "Injury"))
    job = jobs.create_job(connection, land_job(cause_of_loss=["weather"]))
    assert job.values_for("cause_of_loss") == ["Weather"]


def test_list_jobs_filters(connection):
    jobs.create_job(connection, land_job("E1", "2025-12-01", district=["Tararua"]))
    jobs.create_job(connection, land_job("E2", "2026-02-01", district=["Horowhenua"], location=["Hidden Lake"]))
    jobs.create_job(connection, land_job("E3", "2026-04-01", district=["Tararua"]))

    def event_numbers(job_filter):
        return [job.event_number for job in jobs.list_jobs(connection, job_filter)]

    assert event_numbers(JobFilter()) == ["E3", "E2", "E1"]
    assert event_numbers(JobFilter(start_date="2026-01-01")) == ["E3", "E2"]
    assert event_numbers(JobFilter(end_date="2026-02-01")) == ["E2", "E1"]
    assert event_numbers(JobFilter(field_equals={"district": "Tararua"})) == ["E3", "E1"]
    assert event_numbers(JobFilter(text="hidden lake")) == ["E2"]


def test_attendance_totals_split_by_organisation(connection, home_organisation, make_person):
    police = organisations.create_organisation(connection, "Police")
    alice = make_person("Alice", organisation_id=home_organisation.id)
    bob = make_person("Bob", organisation_id=police.id)
    carol = make_person("Carol")
    job = jobs.create_job(connection, land_job())
    jobs.set_attendance(connection, job.id, alice.id, 7)
    jobs.set_attendance(connection, job.id, bob.id, "3.5", role="IC")
    jobs.set_attendance(connection, job.id, carol.id, 2)

    totals = jobs.job_totals(connection, job.id)
    assert totals.person_hours == 12.5
    assert totals.staff_count == 3
    assert totals.hours_by_organisation == {"(no organisation)": 2, "Home Group": 7, "Police": 3.5}


def test_setting_attendance_twice_replaces_hours(connection, make_person):
    alice = make_person("Alice")
    job = jobs.create_job(connection, land_job())
    jobs.set_attendance(connection, job.id, alice.id, 4)
    jobs.set_attendance(connection, job.id, alice.id, 6)
    assert jobs.job_totals(connection, job.id).person_hours == 6


def test_attendance_keeps_organisation_at_time_of_job(connection, home_organisation, make_person):
    from sar_log import people
    from sar_log.people import PersonInput
    other = organisations.create_organisation(connection, "Other Group")
    alice = make_person("Alice", organisation_id=home_organisation.id)
    job = jobs.create_job(connection, land_job())
    jobs.set_attendance(connection, job.id, alice.id, 5)
    people.update_person(connection, alice.id, PersonInput("Alice", organisation_id=other.id))
    assert jobs.job_totals(connection, job.id).hours_by_organisation == {"Home Group": 5}


def test_negative_or_non_numeric_hours_are_rejected(connection, make_person):
    alice = make_person("Alice")
    job = jobs.create_job(connection, land_job())
    with pytest.raises(ValidationError):
        jobs.set_attendance(connection, job.id, alice.id, -1)
    with pytest.raises(ValidationError):
        jobs.set_attendance(connection, job.id, alice.id, "lots")


def test_deleting_job_removes_its_values_and_attendance(connection, make_person):
    alice = make_person("Alice")
    job = jobs.create_job(connection, land_job(location=["Ridge"]))
    jobs.set_attendance(connection, job.id, alice.id, 4)
    jobs.delete_job(connection, job.id)
    with pytest.raises(NotFoundError):
        jobs.get_job(connection, job.id)
    assert connection.execute("SELECT COUNT(*) FROM job_field_value").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM job_attendance").fetchone()[0] == 0
