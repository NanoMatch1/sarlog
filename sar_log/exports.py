"""CSV exports. Excel opens these directly."""

from __future__ import annotations

import csv
import io
import sqlite3

from sar_log.fields import list_field_definitions
from sar_log.jobs import JobFilter, job_totals, list_attendance_for_job, list_jobs
from sar_log.people import list_people
from sar_log.reports import ReportTable
from sar_log.training import list_training_sessions

MULTI_VALUE_SEPARATOR = "; "


def table_to_csv(headings: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headings)
    writer.writerows(rows)
    return buffer.getvalue()


def report_to_csv(report: ReportTable) -> str:
    return table_to_csv(report.headings, report.rows)


def jobs_csv(connection: sqlite3.Connection, job_filter: JobFilter | None = None) -> str:
    """One row per job, one column per field (archived fields included)."""
    definitions = list_field_definitions(connection, include_archived=True)
    headings = ["Event number", "Date", "Name", *[definition.label for definition in definitions],
                "Person hours", "Total staff", "Notes"]
    rows = []
    for job in reversed(list_jobs(connection, job_filter)):
        totals = job_totals(connection, job.id)
        rows.append([
            job.event_number, job.start_date, job.name,
            *[MULTI_VALUE_SEPARATOR.join(job.values_for(definition.key)) for definition in definitions],
            totals.person_hours, totals.staff_count, job.notes,
        ])
    return table_to_csv(headings, rows)


def attendance_csv(connection: sqlite3.Connection, job_filter: JobFilter | None = None) -> str:
    """One row per person per job."""
    rows = []
    for job in reversed(list_jobs(connection, job_filter)):
        for record in list_attendance_for_job(connection, job.id):
            rows.append([job.event_number, job.start_date, record.person_name,
                         record.organisation_name or "", record.hours, record.role])
    return table_to_csv(["Event number", "Date", "Person", "Organisation", "Hours", "Role"], rows)


def people_csv(connection: sqlite3.Connection) -> str:
    rows = [[person.sar_id or "", person.full_name, person.organisation_name or "",
             person.joined_date or "", person.left_date or "", person.email, person.phone,
             person.comments]
            for person in list_people(connection)]
    return table_to_csv(["SAR ID", "Name", "Organisation", "Joined", "Left", "Email", "Phone",
                         "Comments"], rows)


def training_csv(connection: sqlite3.Connection) -> str:
    """One row per person per training session."""
    names = {person.id: person.full_name for person in list_people(connection)}
    rows = []
    for session in reversed(list_training_sessions(connection)):
        for person_id in session.attendee_ids:
            rows.append([session.session_date, session.training_type_name, session.title,
                         names.get(person_id, f"#{person_id}")])
    return table_to_csv(["Date", "Training type", "Title", "Person"], rows)
