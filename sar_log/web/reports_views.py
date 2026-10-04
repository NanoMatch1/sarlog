"""Report page, per-report CSV downloads, and whole-table exports."""

from __future__ import annotations

from typing import Callable

from flask import Blueprint, abort, render_template, request

from sar_log import exports, reports
from sar_log.reports import DateRange, ReportTable
from sar_log.web.helpers import connection, csv_response, query_date

blueprint = Blueprint("reports", __name__)

# report name -> function(date_range) -> ReportTable. Parameters other than
# the date range come from the query string. Registering here makes a report
# downloadable as CSV with no other changes.
REPORT_BUILDERS: dict[str, Callable[[DateRange], ReportTable]] = {}


def register_report(name: str):
    def decorator(builder: Callable[[DateRange], ReportTable]):
        REPORT_BUILDERS[name] = builder
        return builder
    return decorator


@register_report("per_period")
def _per_period(date_range: DateRange) -> ReportTable:
    period = request.args.get("period", "year")
    return reports.jobs_per_period(connection(), date_range, "month" if period == "month" else "year")


@register_report("hours_by_organisation")
def _hours_by_organisation(date_range: DateRange) -> ReportTable:
    return reports.hours_by_organisation(connection(), date_range)


@register_report("hours_by_person")
def _hours_by_person(date_range: DateRange) -> ReportTable:
    return reports.hours_by_person(connection(), date_range)


@register_report("numeric_totals")
def _numeric_totals(date_range: DateRange) -> ReportTable:
    return reports.numeric_field_totals(connection(), date_range)


@register_report("field")
def _field_counts(date_range: DateRange) -> ReportTable:
    return reports.jobs_by_field(connection(), request.args["field_key"], date_range)


@register_report("crosstab")
def _crosstab(date_range: DateRange) -> ReportTable:
    return reports.jobs_crosstab(connection(), request.args["row_field"], request.args["column_field"],
                                 date_range)


def date_range_from_query() -> DateRange:
    return DateRange(start_date=query_date("start_date") or None,
                     end_date=query_date("end_date") or None)


@blueprint.route("/reports")
def reports_page():
    date_range = date_range_from_query()
    countable = reports.countable_fields(connection())
    countable_keys = {definition.key for definition in countable}
    row_field = request.args.get("row_field", "")
    column_field = request.args.get("column_field", "")
    crosstab = (reports.jobs_crosstab(connection(), row_field, column_field, date_range)
                if row_field in countable_keys and column_field in countable_keys else None)
    return render_template(
        "reports.html",
        date_range=date_range,
        period=request.args.get("period", "year"),
        overview=reports.overview(connection(), date_range),
        per_period=_per_period(date_range),
        hours_by_organisation=_hours_by_organisation(date_range),
        hours_by_person=_hours_by_person(date_range),
        numeric_totals=_numeric_totals(date_range),
        field_tables=[(definition.key, reports.jobs_by_field(connection(), definition.key, date_range))
                      for definition in countable],
        countable_fields=countable,
        row_field=row_field,
        column_field=column_field,
        crosstab=crosstab,
    )


@blueprint.route("/reports/download/<report_name>.csv")
def download_report(report_name: str):
    builder = REPORT_BUILDERS.get(report_name)
    if builder is None:
        abort(404)
    report = builder(date_range_from_query())
    return csv_response(exports.report_to_csv(report), f"{report_name}.csv")


# export name -> function producing the CSV text.
EXPORTS: dict[str, Callable[[], str]] = {
    "jobs": lambda: exports.jobs_csv(connection()),
    "attendance": lambda: exports.attendance_csv(connection()),
    "people": lambda: exports.people_csv(connection()),
    "training": lambda: exports.training_csv(connection()),
}


@blueprint.route("/exports")
def exports_page():
    return render_template("exports.html", export_names=list(EXPORTS))


@blueprint.route("/exports/<export_name>.csv")
def download_export(export_name: str):
    if export_name not in EXPORTS:
        abort(404)
    return csv_response(EXPORTS[export_name](), f"sar_{export_name}.csv")
