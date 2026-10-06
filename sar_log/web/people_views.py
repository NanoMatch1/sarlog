"""Pages for people and organisations."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from sar_log import exports, jobs, organisations, people, people_search, training
from sar_log.errors import ValidationError
from sar_log.people import PersonInput
from sar_log.people_search import MEMBERSHIP_CHOICES, TRAINING_STATUS_CHOICES, PersonFilter
from sar_log.web.helpers import (connection, csv_response, form_optional_int, form_text, query_as_of_date,
                                 query_date)

blueprint = Blueprint("people", __name__)


def person_input_from_form() -> PersonInput:
    return PersonInput(
        full_name=form_text("full_name"), sar_id=form_text("sar_id"),
        organisation_id=form_optional_int("organisation_id"),
        joined_date=form_text("joined_date"), left_date=form_text("left_date"),
        email=form_text("email"), phone=form_text("phone"), comments=form_text("comments"),
    )


def person_filter_from_query() -> PersonFilter:
    membership = request.args.get("membership", "active")
    return PersonFilter(
        membership=membership if membership in MEMBERSHIP_CHOICES else "active",
        organisation_id=request.args.get("organisation_id", type=int),
        text=request.args.get("text", "").strip(),
        training_type_id=request.args.get("training_type_id", type=int),
        training_status=request.args.get("training_status", ""),
        trained_since=query_date("trained_since") or None,
        not_trained_since=query_date("not_trained_since") or None,
    )


@blueprint.route("/people")
def list_people_page():
    as_of = query_as_of_date()
    person_filter = person_filter_from_query()
    return render_template(
        "people_list.html", as_of=as_of, person_filter=person_filter,
        summaries=people_search.search_people(connection(), person_filter, as_of),
        organisations=organisations.list_organisations(connection()),
        training_types=training.list_training_types(connection()),
        membership_choices=MEMBERSHIP_CHOICES, training_status_choices=TRAINING_STATUS_CHOICES,
    )


@blueprint.route("/people.csv")
def download_people_page():
    """The people currently shown on the People page, with the same filter."""
    summaries = people_search.search_people(connection(), person_filter_from_query(), query_as_of_date())
    return csv_response(exports.people_csv(connection(), [summary.person for summary in summaries]),
                        "sar_people.csv")


def _render_person_form(person=None, person_input=None, error=None):
    return render_template("person_form.html", person=person, person_input=person_input, error=error,
                           organisations=organisations.list_organisations(connection())), \
        (400 if error else 200)


@blueprint.route("/people/new", methods=["GET", "POST"])
def new_person_page():
    if request.method == "GET":
        return _render_person_form()
    person_input = person_input_from_form()
    try:
        person = people.create_person(connection(), person_input)
    except ValidationError as error:
        return _render_person_form(person_input=person_input, error=str(error))
    flash(f"{person.full_name} added.")
    return redirect(url_for("people.person_detail_page", person_id=person.id))


@blueprint.route("/people/<int:person_id>/edit", methods=["GET", "POST"])
def edit_person_page(person_id: int):
    person = people.get_person(connection(), person_id)
    if request.method == "GET":
        return _render_person_form(person=person)
    person_input = person_input_from_form()
    try:
        people.update_person(connection(), person_id, person_input)
    except ValidationError as error:
        return _render_person_form(person=person, person_input=person_input, error=str(error))
    flash("Saved.")
    return redirect(url_for("people.person_detail_page", person_id=person_id))


@blueprint.route("/people/<int:person_id>")
def person_detail_page(person_id: int):
    person = people.get_person(connection(), person_id)
    job_history = jobs.list_attendance_for_person(connection(), person_id)
    return render_template(
        "person_detail.html", person=person, job_history=job_history,
        service_length=person.service_length(query_as_of_date()),
        total_hours=sum(record.hours for _, record in job_history),
        training_sessions=training.list_sessions_for_person(connection(), person_id),
    )


@blueprint.route("/people/<int:person_id>/delete", methods=["POST"])
def delete_person_page(person_id: int):
    try:
        people.delete_person(connection(), person_id)
    except ValidationError as error:
        flash(str(error))
        return redirect(url_for("people.person_detail_page", person_id=person_id))
    flash("Person deleted.")
    return redirect(url_for("people.list_people_page"))


@blueprint.route("/organisations", methods=["GET", "POST"])
def organisations_page():
    error = None
    if request.method == "POST":
        try:
            organisation_id = form_optional_int("organisation_id")
            if organisation_id is None:
                organisations.create_organisation(connection(), form_text("name"), form_text("notes"))
            else:
                organisations.update_organisation(connection(), organisation_id, form_text("name"),
                                                  form_text("notes"))
            return redirect(url_for("people.organisations_page"))
        except ValidationError as exception:
            error = str(exception)
    return render_template("organisations.html", error=error,
                           organisations=organisations.list_organisations(connection())), \
        (400 if error else 200)
