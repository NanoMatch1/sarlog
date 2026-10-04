import pytest

from sar_log.errors import ValidationError
from sar_log.field_types import FIELD_TYPE_REGISTRY, FieldSpec, get_field_type

LIST_SPEC = FieldSpec(label="Type", choices=("Hunter", "Tramper", "Child"))


def test_every_registered_type_names_a_widget_macro():
    template_text = open("sar_log/web/templates/_field_widgets.html").read()
    for field_type in FIELD_TYPE_REGISTRY.values():
        assert f"macro {field_type.widget}(" in template_text


def test_blank_input_stores_nothing():
    assert get_field_type("text").to_storage(["  ", ""], FieldSpec("Location")) == []


def test_required_blank_input_is_rejected():
    with pytest.raises(ValidationError, match="required"):
        get_field_type("text").to_storage([""], FieldSpec("Location", is_required=True))


def test_single_valued_type_rejects_two_values():
    with pytest.raises(ValidationError, match="single value"):
        get_field_type("text").to_storage(["a", "b"], FieldSpec("Location"))


@pytest.mark.parametrize("raw, stored", [("3", "3"), (" 12 ", "12")])
def test_integer_normalises(raw, stored):
    assert get_field_type("integer").to_storage([raw], FieldSpec("Bodies")) == [stored]


def test_integer_rejects_decimal():
    with pytest.raises(ValidationError, match="whole number"):
        get_field_type("integer").to_storage(["1.5"], FieldSpec("Bodies"))


def test_decimal_normalises():
    assert get_field_type("decimal").to_storage(["1.50"], FieldSpec("Days")) == ["1.5"]


@pytest.mark.parametrize("raw, stored", [("Yes", "yes"), ("x", "yes"), ("1", "yes"), ("No", "no"), ("0", "no")])
def test_boolean_accepts_spreadsheet_style_input(raw, stored):
    assert get_field_type("boolean").to_storage([raw], FieldSpec("PLB")) == [stored]


def test_boolean_rejects_other_words():
    with pytest.raises(ValidationError):
        get_field_type("boolean").to_storage(["maybe"], FieldSpec("PLB"))


def test_date_normalises_and_rejects_bad_dates():
    assert get_field_type("date").to_storage(["2026-02-03"], FieldSpec("Found")) == ["2026-02-03"]
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        get_field_type("date").to_storage(["3/2/2026"], FieldSpec("Found"))


def test_choice_matches_case_insensitively_to_canonical_spelling():
    assert get_field_type("choice").to_storage(["hunter"], LIST_SPEC) == ["Hunter"]


def test_choice_rejects_unknown_value_and_lists_options():
    with pytest.raises(ValidationError, match="Options: Hunter, Tramper, Child"):
        get_field_type("choice").to_storage(["Diver"], LIST_SPEC)


def test_multi_choice_keeps_definition_order_and_drops_duplicates():
    stored = get_field_type("multi_choice").to_storage(["Child", "hunter", "Hunter"], LIST_SPEC)
    assert stored == ["Hunter", "Child"]


def test_unknown_type_name_is_a_validation_error():
    with pytest.raises(ValidationError):
        get_field_type("colour")
