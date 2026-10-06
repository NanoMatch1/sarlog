"""The Feedback page: write down problems and ideas while using the app."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

import sar_log
from sar_log import feedback
from sar_log.errors import ValidationError
from sar_log.web.helpers import connection, form_text

blueprint = Blueprint("feedback", __name__)


def safe_local_path(path: str) -> str:
    """The page the user came from, if it is a path within this app."""
    return path if path.startswith("/") and not path.startswith("//") else ""


def _render_feedback_page(form_values: dict, error: str | None = None):
    show_resolved = request.args.get("show") == "all"
    items = feedback.list_feedback(connection(), include_resolved=show_resolved)
    open_items = feedback.list_feedback(connection(), include_resolved=False)
    return render_template(
        "feedback.html", items=items, show_resolved=show_resolved, form_values=form_values,
        error=error, kinds=feedback.FEEDBACK_KINDS, open_count=len(open_items),
        open_items_text=feedback.feedback_as_text(open_items),
    ), (400 if error else 200)


@blueprint.route("/feedback", methods=["GET", "POST"])
def feedback_page():
    if request.method == "GET":
        return _render_feedback_page({"page": safe_local_path(request.args.get("from_page", "")),
                                      "kind": "", "message": ""})
    form_values = {"page": safe_local_path(form_text("page")), "kind": form_text("kind"),
                   "message": form_text("message")}
    try:
        feedback.create_feedback(connection(), form_values["kind"], form_values["message"],
                                 page=form_values["page"], app_version=sar_log.__version__)
    except ValidationError as exception:
        return _render_feedback_page(form_values, str(exception))
    flash("Thanks, your feedback is saved. It's listed on the Feedback page, ready to send on.")
    return redirect(form_values["page"] or url_for("feedback.feedback_page"))


@blueprint.route("/feedback/<int:feedback_id>/resolve", methods=["POST"])
def resolve_feedback_page(feedback_id: int):
    is_resolved = request.form.get("is_resolved") == "1"
    feedback.set_feedback_resolved(connection(), feedback_id, is_resolved, form_text("resolution"))
    flash(f"Feedback #{feedback_id} marked as {'dealt with' if is_resolved else 'open'}.")
    return redirect(url_for("feedback.feedback_page", show=request.args.get("show")))
