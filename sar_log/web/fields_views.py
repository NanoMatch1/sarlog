"""Pages for managing job field definitions (the user-extensible part of a job)."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from sar_log import fields
from sar_log.errors import ValidationError
from sar_log.field_types import FIELD_TYPE_REGISTRY
from sar_log.web.helpers import connection, form_text

blueprint = Blueprint("fields", __name__)


@blueprint.route("/fields")
def list_fields_page():
    definitions = fields.list_field_definitions(connection(), include_archived=True)
    usage = {definition.key: fields.count_jobs_using_field(connection(), definition.key)
             for definition in definitions}
    return render_template("fields_list.html", definitions=definitions, usage=usage)


def _render_field_form(definition=None, form_values=None, error=None):
    sections = sorted({existing.section for existing in fields.list_field_definitions(connection(), True)})
    return render_template("field_form.html", definition=definition, form_values=form_values or {},
                           error=error, field_types=FIELD_TYPE_REGISTRY, sections=sections), \
        (400 if error else 200)


@blueprint.route("/fields/new", methods=["GET", "POST"])
def new_field_page():
    if request.method == "GET":
        return _render_field_form()
    try:
        definition = fields.create_field_definition(
            connection(), label=form_text("label"), value_type=form_text("value_type"),
            section=form_text("section"), description=form_text("description"),
            choices=fields.parse_choices_text(request.form.get("choices", "")),
            is_required=bool(request.form.get("is_required")),
        )
    except ValidationError as error:
        return _render_field_form(form_values=request.form, error=str(error))
    flash(f"Field '{definition.label}' added. It now appears on every job form.")
    return redirect(url_for("fields.list_fields_page"))


@blueprint.route("/fields/<key>/edit", methods=["GET", "POST"])
def edit_field_page(key: str):
    definition = fields.get_field_definition(connection(), key)
    if request.method == "GET":
        return _render_field_form(definition=definition)
    try:
        fields.update_field_definition(
            connection(), key, label=form_text("label"), section=form_text("section"),
            description=form_text("description"),
            choices=fields.parse_choices_text(request.form.get("choices", "")),
            is_required=bool(request.form.get("is_required")),
            sort_order=int(form_text("sort_order") or definition.sort_order),
        )
    except (ValidationError, ValueError) as error:
        return _render_field_form(definition=definition, form_values=request.form, error=str(error))
    flash("Field saved.")
    return redirect(url_for("fields.list_fields_page"))


@blueprint.route("/fields/<key>/rename-choice", methods=["POST"])
def rename_choice_page(key: str):
    try:
        fields.rename_choice(connection(), key, form_text("old_choice"), form_text("new_choice"))
        flash("Choice renamed on the field and on every job that used it.")
    except ValidationError as error:
        flash(str(error))
    return redirect(url_for("fields.edit_field_page", key=key))


@blueprint.route("/fields/<key>/archive", methods=["POST"])
def archive_field_page(key: str):
    is_archived = request.form.get("archive") == "1"
    fields.set_field_archived(connection(), key, is_archived)
    flash("Field archived: hidden from forms, values kept." if is_archived else "Field restored.")
    return redirect(url_for("fields.list_fields_page"))
