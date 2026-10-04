"""Pages for training types, sessions and the training overview."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from sar_log import people, training
from sar_log.errors import ValidationError
from sar_log.web.helpers import (app_config, connection, form_int_list, form_optional_int,
                                 form_text, query_as_of_date)

blueprint = Blueprint("training", __name__)


@blueprint.route("/training")
def training_overview_page():
    config = app_config()
    as_of = query_as_of_date()
    lapse_months = request.args.get("lapse_months", type=int) or config.training_lapse_months
    statuses = training.member_training_status(
        connection(), as_of, period_months=config.training_period_months, lapse_months=lapse_months)
    return render_template("training_overview.html", as_of=as_of, lapse_months=lapse_months,
                           period_months=config.training_period_months, statuses=statuses,
                           lapsed_count=sum(status.is_lapsed for status in statuses),
                           gaps=training.training_gaps(connection(), as_of))


@blueprint.route("/training/matrix")
def training_matrix_page():
    as_of = query_as_of_date()
    return render_template("training_matrix.html", as_of=as_of,
                           matrix=training.qualification_matrix(connection(), as_of))


@blueprint.route("/training/sessions")
def training_sessions_page():
    names = {person.id: person.full_name for person in people.list_people(connection())}
    return render_template("training_sessions.html", names=names,
                           sessions=training.list_training_sessions(connection()))


def _render_session_form(session=None, form_values=None, error=None):
    # Everyone is listed, active members first, so past sessions can be entered
    # for people who have since left.
    person_list = sorted(people.list_people(connection()),
                         key=lambda person: (person.left_date is not None, person.full_name))
    return render_template("training_session_form.html", session=session, form_values=form_values,
                           error=error, people=person_list,
                           training_types=training.list_training_types(connection())), \
        (400 if error else 200)


def _session_form_values() -> dict:
    return {
        "session_date": form_text("session_date"),
        "training_type_id": form_optional_int("training_type_id"),
        "attendee_ids": form_int_list("attendee_ids"),
        "title": form_text("title"),
        "notes": form_text("notes"),
    }


@blueprint.route("/training/sessions/new", methods=["GET", "POST"])
def new_training_session_page():
    if request.method == "GET":
        return _render_session_form()
    values = _session_form_values()
    try:
        if values["training_type_id"] is None:
            raise ValidationError("Choose a training type")
        training.create_training_session(connection(), **values)
    except ValidationError as error:
        return _render_session_form(form_values=values, error=str(error))
    flash("Training session saved.")
    return redirect(url_for("training.training_sessions_page"))


@blueprint.route("/training/sessions/<int:session_id>/edit", methods=["GET", "POST"])
def edit_training_session_page(session_id: int):
    session = training.get_training_session(connection(), session_id)
    if request.method == "GET":
        return _render_session_form(session=session)
    values = _session_form_values()
    try:
        if values["training_type_id"] is None:
            raise ValidationError("Choose a training type")
        training.update_training_session(connection(), session_id, **values)
    except ValidationError as error:
        return _render_session_form(session=session, form_values=values, error=str(error))
    flash("Training session saved.")
    return redirect(url_for("training.training_sessions_page"))


@blueprint.route("/training/sessions/<int:session_id>/delete", methods=["POST"])
def delete_training_session_page(session_id: int):
    training.delete_training_session(connection(), session_id)
    flash("Training session deleted.")
    return redirect(url_for("training.training_sessions_page"))


@blueprint.route("/training/types", methods=["GET", "POST"])
def training_types_page():
    error = None
    if request.method == "POST":
        try:
            training_type_id = form_optional_int("training_type_id")
            if training_type_id is None:
                training.create_training_type(connection(), form_text("name"), form_text("description"),
                                              form_text("validity_months"))
            else:
                training.update_training_type(connection(), training_type_id, form_text("name"),
                                              form_text("description"), form_text("validity_months"),
                                              is_archived=bool(request.form.get("is_archived")))
            return redirect(url_for("training.training_types_page"))
        except ValidationError as exception:
            error = str(exception)
    return render_template("training_types.html", error=error,
                           training_types=training.list_training_types(connection(), include_archived=True)), \
        (400 if error else 200)
