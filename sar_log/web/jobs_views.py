"""Pages for listing, entering and editing jobs and their attendance."""

from __future__ import annotations

from collections import OrderedDict

from flask import Blueprint, flash, redirect, render_template, request, url_for

from sar_log import jobs
from sar_log.errors import ValidationError
from sar_log.fields import FieldDefinition, list_field_definitions
from sar_log.jobs import JobFilter, JobInput
from sar_log.people import list_people
from sar_log.web.helpers import connection, form_optional_int, form_text, query_date

blueprint = Blueprint("jobs", __name__)

FIELD_INPUT_PREFIX = "field__"
FILTER_INPUT_PREFIX = "filter__"


def definitions_by_section(definitions: list[FieldDefinition]) -> "OrderedDict[str, list[FieldDefinition]]":
    sections: OrderedDict[str, list[FieldDefinition]] = OrderedDict()
    for definition in definitions:
        sections.setdefault(definition.section, []).append(definition)
    return sections


def job_input_from_form(definitions: list[FieldDefinition]) -> JobInput:
    """Every active field is read, so clearing an input clears the stored value."""
    return JobInput(
        event_number=form_text("event_number"),
        start_date=form_text("start_date"),
        name=form_text("name"),
        notes=form_text("notes"),
        raw_field_values={
            definition.key: request.form.getlist(FIELD_INPUT_PREFIX + definition.key)
            for definition in definitions
        },
    )


def job_filter_from_query() -> JobFilter:
    return JobFilter(
        start_date=query_date("start_date") or None,
        end_date=query_date("end_date") or None,
        text=request.args.get("text", ""),
        field_equals={
            name[len(FILTER_INPUT_PREFIX):]: value
            for name, value in request.args.items()
            if name.startswith(FILTER_INPUT_PREFIX) and value
        },
    )


@blueprint.route("/jobs")
def list_jobs_page():
    definitions = list_field_definitions(connection())
    job_filter = job_filter_from_query()
    job_list = jobs.list_jobs(connection(), job_filter)
    totals = {job.id: jobs.job_totals(connection(), job.id) for job in job_list}
    filterable = [definition for definition in definitions if definition.field_type.is_countable]
    summary_fields = [definition for definition in definitions
                      if definition.key in ("environment", "district", "lost_party_type")]
    return render_template("jobs_list.html", jobs=job_list, totals=totals, job_filter=job_filter,
                           filterable_fields=filterable, summary_fields=summary_fields)


def _render_job_form(definitions, job=None, job_input=None, error=None):
    return render_template(
        "job_form.html", job=job, job_input=job_input, error=error,
        sections=definitions_by_section(definitions), field_prefix=FIELD_INPUT_PREFIX,
    ), (400 if error else 200)


@blueprint.route("/jobs/new", methods=["GET", "POST"])
def new_job_page():
    definitions = list_field_definitions(connection())
    if request.method == "GET":
        return _render_job_form(definitions)
    job_input = job_input_from_form(definitions)
    try:
        job = jobs.create_job(connection(), job_input)
    except ValidationError as error:
        return _render_job_form(definitions, job_input=job_input, error=str(error))
    flash(f"Job {job.event_number} created. Add the people who attended below.")
    return redirect(url_for("jobs.job_detail_page", job_id=job.id))


@blueprint.route("/jobs/<int:job_id>/edit", methods=["GET", "POST"])
def edit_job_page(job_id: int):
    definitions = list_field_definitions(connection())
    job = jobs.get_job(connection(), job_id)
    if request.method == "GET":
        return _render_job_form(definitions, job=job)
    job_input = job_input_from_form(definitions)
    try:
        jobs.update_job(connection(), job_id, job_input)
    except ValidationError as error:
        return _render_job_form(definitions, job=job, job_input=job_input, error=str(error))
    flash("Job saved.")
    return redirect(url_for("jobs.job_detail_page", job_id=job_id))


@blueprint.route("/jobs/<int:job_id>")
def job_detail_page(job_id: int):
    job = jobs.get_job(connection(), job_id)
    definitions = list_field_definitions(connection(), include_archived=True)
    # Show archived fields only if this job has a value for them.
    shown = [definition for definition in definitions
             if not definition.is_archived or job.values_for(definition.key)]
    attendance = jobs.list_attendance_for_job(connection(), job_id)
    attended_ids = {record.person_id for record in attendance}
    available_people = [person for person in list_people(connection()) if person.id not in attended_ids]
    return render_template("job_detail.html", job=job, sections=definitions_by_section(shown),
                           attendance=attendance, totals=jobs.compute_totals(attendance),
                           available_people=available_people,
                           error=request.args.get("error"))


@blueprint.route("/jobs/<int:job_id>/delete", methods=["POST"])
def delete_job_page(job_id: int):
    job = jobs.get_job(connection(), job_id)
    if form_text("confirm_event_number") != job.event_number:
        flash("Type the event number to confirm deletion. Nothing was deleted.")
        return redirect(url_for("jobs.job_detail_page", job_id=job_id))
    jobs.delete_job(connection(), job_id)
    flash(f"Job {job.event_number} deleted.")
    return redirect(url_for("jobs.list_jobs_page"))


@blueprint.route("/jobs/<int:job_id>/attendance", methods=["POST"])
def set_attendance_page(job_id: int):
    person_id = form_optional_int("person_id")
    try:
        if person_id is None:
            raise ValidationError("Choose a person")
        jobs.set_attendance(connection(), job_id, person_id, form_text("hours"), form_text("role"))
    except ValidationError as error:
        return redirect(url_for("jobs.job_detail_page", job_id=job_id, error=str(error)))
    return redirect(url_for("jobs.job_detail_page", job_id=job_id) + "#attendance")


@blueprint.route("/jobs/<int:job_id>/attendance/<int:attendance_id>/delete", methods=["POST"])
def remove_attendance_page(job_id: int, attendance_id: int):
    jobs.remove_attendance(connection(), attendance_id)
    return redirect(url_for("jobs.job_detail_page", job_id=job_id) + "#attendance")
