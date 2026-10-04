"""Headless workflow tests: drive the web app the way a data-entry volunteer would.

Each test goes through the real routes, forms and templates via Flask's test
client, then checks what the user would see on the resulting pages.
"""

import html
import re

import pytest

from sar_log.web import create_app


@pytest.fixture
def client(app_config):
    app = create_app(app_config)
    app.config["TESTING"] = True
    return app.test_client()


def page_text(response) -> str:
    """Visible text of a page with tags stripped, for readable assertions."""
    without_tags = re.sub(r"<[^>]+>", " ", response.get_data(as_text=True))
    return re.sub(r"\s+", " ", html.unescape(without_tags))


def created_id(response, kind: str) -> int:
    return int(re.search(rf"/{kind}/(\d+)", response.headers["Location"]).group(1))


def add_organisation(client, name):
    response = client.post("/organisations", data={"name": name})
    assert response.status_code == 302


def organisation_id(client, name):
    html = client.get("/people/new").get_data(as_text=True)
    return re.search(rf'<option value="(\d+)"\s*>{name}</option>', html).group(1)


def add_person(client, full_name, organisation_name=None, **extra):
    data = {"full_name": full_name, **extra}
    if organisation_name:
        data["organisation_id"] = organisation_id(client, organisation_name)
    # Follow the redirect so the "added" flash message is consumed here and
    # does not leak into the next page the test inspects.
    response = client.post("/people/new", data=data, follow_redirects=True)
    assert response.status_code == 200 and response.request.path.startswith("/people/"), page_text(response)
    return int(response.request.path.rsplit("/", 1)[1])


def test_full_job_logging_workflow(client):
    add_organisation(client, "Home Group")
    add_organisation(client, "Police")
    alice = add_person(client, "Alice Example", "Home Group", joined_date="2020-01-01")
    bob = add_person(client, "Bob Example", "Police")

    # A new detail comes to light: add a field for it from the Fields page.
    response = client.post("/fields/new", data={
        "label": "Cause of loss", "value_type": "choice", "section": "Lost party",
        "choices": "Weather\nInjury\nNavigation error"})
    assert response.status_code == 302
    assert "Cause of loss" in page_text(client.get("/jobs/new"))

    # Submitting without the required Environment shows an error and keeps input.
    response = client.post("/jobs/new", data={"event_number": "P-2026-01", "start_date": "2026-03-14",
                                              "field__location": "Ridge Track"})
    assert response.status_code == 400
    assert "'Environment' is required" in page_text(response)
    assert 'value="Ridge Track"' in response.get_data(as_text=True)

    response = client.post("/jobs/new", data={
        "event_number": "P-2026-01", "start_date": "2026-03-14", "name": "Overdue tramper",
        "field__environment": "Land", "field__district": "Tararua", "field__location": "Ridge Track",
        "field__lost_party_type": ["Tramper", "Day walker"], "field__plb": "no",
        "field__cause_of_loss": "Weather", "notes": "Found near the hut."})
    assert response.status_code == 302
    job_id = created_id(response, "jobs")

    client.post(f"/jobs/{job_id}/attendance", data={"person_id": alice, "hours": "7.5", "role": "Field team"})
    client.post(f"/jobs/{job_id}/attendance", data={"person_id": bob, "hours": "3"})
    detail = page_text(client.get(f"/jobs/{job_id}"))
    assert "10.5 Person hours" in detail
    assert "2 Total staff" in detail
    assert "7.5 hours · Home Group" in detail and "3.0 hours · Police" in detail
    assert "Day walker, Tramper" in detail  # choice-list order, not entry order
    assert "Weather" in detail

    # Bad hours are reported, not stored.
    response = client.post(f"/jobs/{job_id}/attendance", data={"person_id": alice, "hours": "lots"},
                           follow_redirects=True)
    assert "Hours must be a number" in page_text(response)

    # Edit: clearing an optional field removes it; other fields stay.
    response = client.post(f"/jobs/{job_id}/edit", data={
        "event_number": "P-2026-01", "start_date": "2026-03-14", "name": "Overdue tramper",
        "field__environment": "Land", "field__district": "Tararua", "field__location": "",
        "field__lost_party_type": ["Tramper"], "field__cause_of_loss": "Weather"})
    assert response.status_code == 302
    detail = page_text(client.get(f"/jobs/{job_id}"))
    assert "Ridge Track" not in detail and "Day walker" not in detail

    # The job list, filters and person page reflect it.
    assert "P-2026-01" in page_text(client.get("/jobs?filter__district=Tararua"))
    assert "P-2026-01" not in page_text(client.get("/jobs?filter__district=Horowhenua"))
    person_page = page_text(client.get(f"/people/{alice}"))
    assert "P-2026-01" in person_page and "7.5 Person hours" in person_page

    # Reports: counts per field, hours per organisation, cross-tab and CSV.
    reports_page = page_text(client.get("/reports?row_field=cause_of_loss&column_field=district"))
    assert "Jobs by Cause of loss" in reports_page
    assert "Cause of loss by District" in reports_page
    assert "Home Group 7.5 1 1" in reports_page
    csv_text = client.get("/reports/download/field.csv?field_key=cause_of_loss").get_data(as_text=True)
    assert "Weather,1,100.0" in csv_text
    jobs_csv = client.get("/exports/jobs.csv").get_data(as_text=True)
    assert jobs_csv.startswith("﻿Event number") and "P-2026-01" in jobs_csv

    # Every change is in the history.
    assert "job_attendance" in page_text(client.get("/changes"))

    # Deleting needs the event number typed in.
    client.post(f"/jobs/{job_id}/delete", data={"confirm_event_number": "wrong"})
    assert client.get(f"/jobs/{job_id}").status_code == 200
    client.post(f"/jobs/{job_id}/delete", data={"confirm_event_number": "P-2026-01"})
    assert client.get(f"/jobs/{job_id}").status_code == 404


def test_training_workflow(client):
    alice = add_person(client, "Alice Example", joined_date="2020-01-01")
    add_person(client, "Bob Example", joined_date="2020-01-01")

    client.post("/training/types", data={"name": "First aid", "validity_months": "24"})
    client.post("/training/types", data={"name": "River safety"})
    first_aid_id = re.search(r'<option value="(\d+)"\s*>First aid</option>',
                             client.get("/training/sessions/new").get_data(as_text=True)).group(1)

    response = client.post("/training/sessions/new", data={"session_date": "2026-05-01",
                                                           "training_type_id": first_aid_id,
                                                           "attendee_ids": [alice], "title": "Refresher"})
    assert response.status_code == 302

    # Missing type is an error, and the ticked attendees survive the round trip.
    response = client.post("/training/sessions/new", data={"session_date": "2026-05-02", "attendee_ids": [alice]})
    assert response.status_code == 400 and "Choose a training type" in page_text(response)
    assert re.search(rf'value="{alice}" checked', response.get_data(as_text=True))

    overview = page_text(client.get("/training?as_of=2026-06-30"))
    assert "1 lapsed" in overview
    assert re.search(r"Bob Example lapsed never", overview)
    assert re.search(r"Alice Example ok 2026-05-01 60 1", overview)
    assert re.search(r"First aid 1 0 1 50%", overview)
    assert re.search(r"River safety 0 0 2 0%", overview)

    matrix = page_text(client.get("/training/matrix?as_of=2026-06-30"))
    assert "2026-05-01" in matrix
    assert "Refresher" in page_text(client.get(f"/people/{alice}"))
    assert "First aid,Refresher,Alice Example" in client.get("/exports/training.csv").get_data(as_text=True)


def test_field_management_workflow(client):
    client.post("/jobs/new", data={"event_number": "E1", "start_date": "2026-01-01",
                                   "field__environment": "Land", "field__district": "Horowhenua"})

    # Removing a choice that's in use is refused with an explanation.
    edit_data = {"label": "District", "section": "Incident", "description": "", "sort_order": "10",
                 "choices": "Palmerston North\nTararua\nOther"}
    response = client.post("/fields/district/edit", data=edit_data)
    assert response.status_code == 400 and "still used" in page_text(response)

    # Renaming updates the jobs too.
    client.post("/fields/district/rename-choice", data={"old_choice": "Horowhenua", "new_choice": "Horo"})
    assert "Horo" in page_text(client.get("/jobs/1"))

    # Archiving hides the field from the form but keeps the value on the job.
    client.post("/fields/district/archive", data={"archive": "1"})
    assert 'name="field__district"' not in client.get("/jobs/new").get_data(as_text=True)
    assert "Horo" in page_text(client.get("/jobs/1"))
    client.post("/fields/district/archive", data={"archive": "0"})
    assert 'name="field__district"' in client.get("/jobs/new").get_data(as_text=True)


def test_person_validation_and_left_members(client):
    response = client.post("/people/new", data={"full_name": "Alice", "joined_date": "2026-01-01",
                                                "left_date": "2025-01-01"})
    assert response.status_code == 400 and "before" in page_text(response)
    add_person(client, "Departed Person", left_date="2025-01-01")
    assert "Departed Person" not in page_text(client.get("/people"))
    assert "Departed Person" in page_text(client.get("/people?show=all"))


def test_every_page_renders_with_demo_data(app_config):
    from sar_log.database import open_database
    from sar_log.demo_data import populate_demo_data
    connection = open_database(app_config.database_path)
    populate_demo_data(connection)
    connection.close()
    client = create_app(app_config).test_client()
    for url in ["/jobs", "/jobs/new", "/jobs/1", "/jobs/1/edit", "/people", "/people/1", "/people/1/edit",
                "/organisations", "/training", "/training/matrix", "/training/sessions",
                "/training/sessions/new", "/training/sessions/1/edit", "/training/types",
                "/reports", "/reports?period=month&row_field=lost_party_type&column_field=district",
                "/exports", "/fields", "/fields/new", "/fields/lost_party_type/edit", "/changes"]:
        assert client.get(url).status_code == 200, url
    for report_url in ["per_period", "hours_by_organisation", "hours_by_person", "numeric_totals"]:
        assert client.get(f"/reports/download/{report_url}.csv").status_code == 200


def test_requests_from_other_hosts_or_sites_are_refused(client):
    # DNS-rebinding style request: wrong Host header.
    assert client.get("/jobs", headers={"Host": "evil.example"}).status_code == 403
    # Cross-site form post.
    response = client.post("/organisations", data={"name": "X"}, headers={"Origin": "http://evil.example"})
    assert response.status_code == 403
    assert client.get("/jobs", headers={"Host": "127.0.0.1:8765"}).status_code == 200
