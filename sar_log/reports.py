"""Job statistics over a date range.

Every report returns a ``ReportTable`` (headings + rows), so the web page,
CSV download and any future export render all reports the same way.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass

from sar_log.fields import FieldDefinition, get_field_definition, list_field_definitions
from sar_log.jobs import (UNASSIGNED_ORGANISATION, Job, JobFilter, compute_totals,
                          list_attendance_for_job, list_jobs)

NOT_RECORDED = "(not recorded)"


@dataclass(frozen=True)
class DateRange:
    start_date: str | None = None
    end_date: str | None = None

    def as_job_filter(self) -> JobFilter:
        return JobFilter(start_date=self.start_date, end_date=self.end_date)


@dataclass(frozen=True)
class ReportTable:
    title: str
    headings: list[str]
    rows: list[list]
    note: str = ""


def countable_fields(connection: sqlite3.Connection) -> list[FieldDefinition]:
    return [definition for definition in list_field_definitions(connection)
            if definition.field_type.is_countable]


def numeric_fields(connection: sqlite3.Connection) -> list[FieldDefinition]:
    return [definition for definition in list_field_definitions(connection)
            if definition.field_type.is_numeric]


def _ordered_values(definition: FieldDefinition, counts: Counter) -> list[str]:
    """Defined choices first (in definition order), then any other stored values."""
    if definition.field_type.uses_choices:
        known = list(definition.choices)
    elif definition.value_type == "boolean":
        known = ["yes", "no"]
    else:
        known = []
    extras = sorted(value for value in counts if value not in known and value != NOT_RECORDED)
    return known + extras + ([NOT_RECORDED] if counts.get(NOT_RECORDED) else [])


def _job_values(job: Job, field_key: str) -> list[str]:
    return job.values_for(field_key) or [NOT_RECORDED]


def jobs_by_field(connection: sqlite3.Connection, field_key: str, date_range: DateRange) -> ReportTable:
    """Number of jobs per value of one field (the old 'sum at the bottom of the column')."""
    definition = get_field_definition(connection, field_key)
    jobs = list_jobs(connection, date_range.as_job_filter())
    counts: Counter = Counter()
    for job in jobs:
        counts.update(_job_values(job, field_key))
    rows = [[value, counts[value], _percent(counts[value], len(jobs))]
            for value in _ordered_values(definition, counts)]
    note = ("Jobs can have several values, so percentages can add to more than 100."
            if definition.field_type.is_multi_valued else "")
    return ReportTable(f"Jobs by {definition.label}", [definition.label, "Jobs", "% of jobs"],
                       rows, note)


def jobs_crosstab(connection: sqlite3.Connection, row_field_key: str, column_field_key: str,
                  date_range: DateRange) -> ReportTable:
    """Count of jobs for each combination of two fields, e.g. lost party type by district."""
    row_definition = get_field_definition(connection, row_field_key)
    column_definition = get_field_definition(connection, column_field_key)
    jobs = list_jobs(connection, date_range.as_job_filter())
    pair_counts: Counter = Counter()
    row_counts: Counter = Counter()
    column_counts: Counter = Counter()
    for job in jobs:
        for row_value in _job_values(job, row_field_key):
            row_counts[row_value] += 1
            for column_value in _job_values(job, column_field_key):
                pair_counts[(row_value, column_value)] += 1
        column_counts.update(_job_values(job, column_field_key))
    row_values = _ordered_values(row_definition, row_counts)
    column_values = _ordered_values(column_definition, column_counts)
    rows = [[row_value, *[pair_counts[(row_value, column_value)] for column_value in column_values],
             row_counts[row_value]]
            for row_value in row_values]
    return ReportTable(f"{row_definition.label} by {column_definition.label}",
                       [row_definition.label, *column_values, "Total"], rows)


def jobs_per_period(connection: sqlite3.Connection, date_range: DateRange,
                    period: str = "year") -> ReportTable:
    """Jobs, person hours and days per year or per month."""
    if period not in ("year", "month"):
        raise ValueError(f"period must be 'year' or 'month', got {period!r}")
    key_length = 4 if period == "year" else 7
    totals: dict[str, list[float]] = defaultdict(lambda: [0, 0.0, 0.0])
    for job in list_jobs(connection, date_range.as_job_filter()):
        bucket = totals[job.start_date[:key_length]]
        bucket[0] += 1
        bucket[1] += compute_totals(list_attendance_for_job(connection, job.id)).person_hours
        bucket[2] += _number(job.values_for("days"))
    rows = [[period_key, values[0], round(values[1], 1), round(values[2], 1)]
            for period_key, values in sorted(totals.items())]
    return ReportTable(f"Jobs per {period}", [period.capitalize(), "Jobs", "Person hours", "Days"], rows)


def hours_by_organisation(connection: sqlite3.Connection, date_range: DateRange) -> ReportTable:
    hours: dict[str, float] = defaultdict(float)
    people: dict[str, set[int]] = defaultdict(set)
    jobs_attended: dict[str, set[int]] = defaultdict(set)
    for job in list_jobs(connection, date_range.as_job_filter()):
        for record in list_attendance_for_job(connection, job.id):
            organisation = record.organisation_name or UNASSIGNED_ORGANISATION
            hours[organisation] += record.hours
            people[organisation].add(record.person_id)
            jobs_attended[organisation].add(job.id)
    rows = [[organisation, round(hours[organisation], 1), len(people[organisation]),
             len(jobs_attended[organisation])]
            for organisation in sorted(hours, key=lambda name: -hours[name])]
    return ReportTable("Person hours by organisation",
                       ["Organisation", "Person hours", "People", "Jobs"], rows)


def hours_by_person(connection: sqlite3.Connection, date_range: DateRange) -> ReportTable:
    hours: dict[int, float] = defaultdict(float)
    job_counts: Counter = Counter()
    names: dict[int, str] = {}
    for job in list_jobs(connection, date_range.as_job_filter()):
        for record in list_attendance_for_job(connection, job.id):
            hours[record.person_id] += record.hours
            job_counts[record.person_id] += 1
            names[record.person_id] = record.person_name
    rows = [[names[person_id], job_counts[person_id], round(hours[person_id], 1)]
            for person_id in sorted(hours, key=lambda person_id: (-hours[person_id], names[person_id]))]
    return ReportTable("Person hours by person", ["Person", "Jobs", "Person hours"], rows)


def numeric_field_totals(connection: sqlite3.Connection, date_range: DateRange) -> ReportTable:
    """Sum and count of every numeric field (days, bodies, ...)."""
    jobs = list_jobs(connection, date_range.as_job_filter())
    rows = []
    for definition in numeric_fields(connection):
        recorded = [_number(job.values_for(definition.key)) for job in jobs
                    if job.values_for(definition.key)]
        rows.append([definition.label, len(recorded), round(sum(recorded), 1)])
    return ReportTable("Numeric field totals", ["Field", "Jobs recorded", "Total"], rows)


@dataclass(frozen=True)
class Overview:
    job_count: int
    person_hours: float
    attendance_count: int
    distinct_people: int


def overview(connection: sqlite3.Connection, date_range: DateRange) -> Overview:
    jobs = list_jobs(connection, date_range.as_job_filter())
    person_hours, attendance_count, people = 0.0, 0, set()
    for job in jobs:
        for record in list_attendance_for_job(connection, job.id):
            person_hours += record.hours
            attendance_count += 1
            people.add(record.person_id)
    return Overview(len(jobs), round(person_hours, 1), attendance_count, len(people))


def _number(values: list[str]) -> float:
    return float(values[0]) if values else 0.0


def _percent(count: int, total: int) -> float:
    return round(100 * count / total, 1) if total else 0.0
