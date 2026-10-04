import csv
import io

import pytest

from sar_log import exports, jobs, organisations, reports, training
from sar_log.jobs import JobInput
from sar_log.reports import DateRange, NOT_RECORDED


@pytest.fixture
def three_jobs(connection, home_organisation, make_person):
    police = organisations.create_organisation(connection, "Police")
    alice = make_person("Alice", organisation_id=home_organisation.id)
    bob = make_person("Bob", organisation_id=police.id)
    first = jobs.create_job(connection, JobInput("E1", "2025-11-01", raw_field_values={
        "environment": ["Land"], "district": ["Tararua"], "lost_party_type": ["Tramper", "Child"],
        "days": ["2"], "bodies": ["1"]}))
    second = jobs.create_job(connection, JobInput("E2", "2026-01-15", raw_field_values={
        "environment": ["Marine"], "district": ["Horowhenua"], "lost_party_type": ["Tramper"], "days": ["1"]}))
    jobs.create_job(connection, JobInput("E3", "2026-02-20", raw_field_values={"environment": ["Land"]}))
    jobs.set_attendance(connection, first.id, alice.id, 8)
    jobs.set_attendance(connection, first.id, bob.id, 4)
    jobs.set_attendance(connection, second.id, alice.id, 3)
    return connection


def rows_as_dict(report):
    return {row[0]: row[1:] for row in report.rows}


def test_jobs_by_field_counts_choices_in_order_with_not_recorded(three_jobs):
    report = reports.jobs_by_field(three_jobs, "district", DateRange())
    assert [row[0] for row in report.rows] == ["Palmerston North", "Horowhenua", "Tararua", "Other", NOT_RECORDED]
    assert rows_as_dict(report)["Tararua"] == [1, 33.3]
    assert rows_as_dict(report)[NOT_RECORDED] == [1, 33.3]


def test_multi_choice_counts_each_selection(three_jobs):
    report = rows_as_dict(reports.jobs_by_field(three_jobs, "lost_party_type", DateRange()))
    assert report["Tramper"][0] == 2
    assert report["Child"][0] == 1


def test_date_range_limits_reports(three_jobs):
    report = rows_as_dict(reports.jobs_by_field(three_jobs, "environment", DateRange("2026-01-01", "2026-12-31")))
    assert report["Land"][0] == 1 and report["Marine"][0] == 1


def test_crosstab(three_jobs):
    report = reports.jobs_crosstab(three_jobs, "lost_party_type", "environment", DateRange())
    assert report.headings[:3] == ["Lost party type", "Land", "Marine"]
    table = rows_as_dict(report)
    assert table["Tramper"][:2] == [1, 1]
    assert table["Tramper"][-1] == 2


def test_jobs_per_period(three_jobs):
    assert reports.jobs_per_period(three_jobs, DateRange(), "year").rows == [
        ["2025", 1, 12.0, 2.0], ["2026", 2, 3.0, 1.0]]
    assert [row[0] for row in reports.jobs_per_period(three_jobs, DateRange(), "month").rows] == [
        "2025-11", "2026-01", "2026-02"]


def test_hours_reports(three_jobs):
    by_organisation = rows_as_dict(reports.hours_by_organisation(three_jobs, DateRange()))
    assert by_organisation == {"Home Group": [11.0, 1, 2], "Police": [4.0, 1, 1]}
    assert reports.hours_by_person(three_jobs, DateRange()).rows == [["Alice", 2, 11.0], ["Bob", 1, 4.0]]
    overview = reports.overview(three_jobs, DateRange())
    assert (overview.job_count, overview.person_hours, overview.attendance_count, overview.distinct_people) == (3, 15.0, 3, 2)


def test_numeric_totals(three_jobs):
    totals = rows_as_dict(reports.numeric_field_totals(three_jobs, DateRange()))
    assert totals["Days"] == [2, 3.0]
    assert totals["Bodies"] == [1, 1.0]


def parse_csv(text):
    return list(csv.reader(io.StringIO(text)))


def test_jobs_csv_has_one_column_per_field_and_computed_totals(three_jobs):
    rows = parse_csv(exports.jobs_csv(three_jobs))
    headings = rows[0]
    first_job = dict(zip(headings, rows[1]))
    assert first_job["Event number"] == "E1"
    assert first_job["Lost party type"] == "Tramper; Child"
    assert first_job["Person hours"] == "12.0"
    assert first_job["Total staff"] == "2"


def test_attendance_people_and_training_csv(three_jobs, make_person):
    assert len(parse_csv(exports.attendance_csv(three_jobs))) == 4
    assert parse_csv(exports.people_csv(three_jobs))[1][1] == "Alice"
    river = training.create_training_type(three_jobs, "River safety")
    alice_id = three_jobs.execute("SELECT id FROM person WHERE full_name = 'Alice'").fetchone()[0]
    training.create_training_session(three_jobs, "2026-01-01", river.id, [alice_id])
    assert parse_csv(exports.training_csv(three_jobs))[1] == ["2026-01-01", "River safety", "", "Alice"]
