import pytest

from sar_log import fields, jobs
from sar_log.default_fields import DEFAULT_FIELDS
from sar_log.database import initialise
from sar_log.errors import ValidationError
from sar_log.jobs import JobInput


def test_defaults_are_seeded_once_and_edits_survive_reinitialising(connection):
    assert len(fields.list_field_definitions(connection)) == len(DEFAULT_FIELDS)
    district = fields.get_field_definition(connection, "district")
    fields.update_field_definition(connection, "district", "District name", district.section,
                                   "", district.choices, False, district.sort_order)
    initialise(connection)
    assert len(fields.list_field_definitions(connection)) == len(DEFAULT_FIELDS)
    assert fields.get_field_definition(connection, "district").label == "District name"


def test_create_field_derives_unique_key(connection):
    first = fields.create_field_definition(connection, "Cause of loss", "text")
    second = fields.create_field_definition(connection, "Cause of loss!", "text")
    assert (first.key, second.key) == ("cause_of_loss", "cause_of_loss_2")


def test_list_field_requires_choices_and_plain_field_rejects_them(connection):
    with pytest.raises(ValidationError, match="at least one choice"):
        fields.create_field_definition(connection, "Weather", "choice")
    with pytest.raises(ValidationError, match="Only list fields"):
        fields.create_field_definition(connection, "Weather", "text", choices=("Rain",))


def test_parse_choices_text_drops_blanks_and_case_duplicates():
    assert fields.parse_choices_text("Rain\n\n rain \nSnow\n") == ("Rain", "Snow")


def test_cannot_remove_choice_in_use_but_can_rename_it(connection):
    jobs.create_job(connection, JobInput("E1", "2026-01-01",
                                         raw_field_values={"environment": ["Land"], "district": ["Tararua"]}))
    district = fields.get_field_definition(connection, "district")
    without_tararua = tuple(choice for choice in district.choices if choice != "Tararua")
    with pytest.raises(ValidationError, match="still used"):
        fields.update_field_definition(connection, "district", district.label, district.section, "",
                                       without_tararua, False, district.sort_order)

    fields.rename_choice(connection, "district", "Tararua", "Tararua District")
    assert "Tararua District" in fields.get_field_definition(connection, "district").choices
    assert jobs.list_jobs(connection)[0].values_for("district") == ["Tararua District"]


def test_rename_choice_rejects_clash(connection):
    with pytest.raises(ValidationError, match="already a choice"):
        fields.rename_choice(connection, "district", "Tararua", "horowhenua")


def test_archived_field_is_hidden_but_values_are_kept(connection):
    job = jobs.create_job(connection, JobInput("E1", "2026-01-01",
                                               raw_field_values={"environment": ["Land"], "location": ["Ridge"]}))
    fields.set_field_archived(connection, "location", True)
    assert "location" not in {definition.key for definition in fields.list_field_definitions(connection)}
    assert jobs.get_job(connection, job.id).values_for("location") == ["Ridge"]
    assert fields.count_jobs_using_field(connection, "location") == 1
