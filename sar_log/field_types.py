"""Value types available to job field definitions.

Each type knows how to turn raw form input into stored text, how to show the
stored value, and which form widget to draw. Types register themselves with
``@register_field_type``; that registry is the only list of types, so adding a
type means adding one class here and one widget macro in
``web/templates/_field_widgets.html``.

Storage is always a list of strings: an empty list means "no value", and only
multi-choice fields ever store more than one string.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Callable, ClassVar

from sar_log.errors import ValidationError

FIELD_TYPE_REGISTRY: dict[str, "FieldType"] = {}


def register_field_type(type_name: str, label: str) -> Callable[[type], type]:
    """Class decorator that instantiates a FieldType and registers it."""

    def decorator(field_type_class: type) -> type:
        if type_name in FIELD_TYPE_REGISTRY:
            raise RuntimeError(f"Field type {type_name!r} registered twice")
        field_type_class.type_name = type_name
        field_type_class.label = label
        FIELD_TYPE_REGISTRY[type_name] = field_type_class()
        return field_type_class

    return decorator


def get_field_type(type_name: str) -> "FieldType":
    try:
        return FIELD_TYPE_REGISTRY[type_name]
    except KeyError:
        raise ValidationError(f"Unknown field type {type_name!r}") from None


@dataclass(frozen=True)
class FieldSpec:
    """The parts of a field definition a type needs to validate a value."""

    label: str
    choices: tuple[str, ...] = ()
    is_required: bool = False


class FieldType:
    type_name: ClassVar[str]
    label: ClassVar[str]
    uses_choices: ClassVar[bool] = False
    is_multi_valued: ClassVar[bool] = False
    # Countable types can be tallied in "jobs per value" reports.
    is_countable: ClassVar[bool] = False
    # Numeric types can be summed in reports.
    is_numeric: ClassVar[bool] = False
    # Name of the macro in web/templates/_field_widgets.html that draws the input.
    widget: ClassVar[str] = "text_input"

    def to_storage(self, raw_values: list[str], spec: FieldSpec) -> list[str]:
        """Validate raw form input and return the strings to store."""
        cleaned = [value.strip() for value in raw_values if value and value.strip()]
        if not cleaned:
            if spec.is_required:
                raise ValidationError(f"'{spec.label}' is required")
            return []
        if len(cleaned) > 1 and not self.is_multi_valued:
            raise ValidationError(f"'{spec.label}' takes a single value")
        return [self.normalise_one(value, spec) for value in cleaned]

    def normalise_one(self, value: str, spec: FieldSpec) -> str:
        return value

    def to_display(self, stored_values: list[str]) -> str:
        return ", ".join(stored_values)


@register_field_type("text", "Short text")
class TextFieldType(FieldType):
    pass


@register_field_type("long_text", "Long text")
class LongTextFieldType(FieldType):
    widget = "textarea_input"


@register_field_type("integer", "Whole number")
class IntegerFieldType(FieldType):
    widget = "number_input"
    is_numeric = True

    def normalise_one(self, value: str, spec: FieldSpec) -> str:
        try:
            return str(int(value))
        except ValueError:
            raise ValidationError(f"'{spec.label}' must be a whole number, got {value!r}") from None


@register_field_type("decimal", "Decimal number")
class DecimalFieldType(FieldType):
    widget = "number_input"
    is_numeric = True

    def normalise_one(self, value: str, spec: FieldSpec) -> str:
        try:
            number = float(value)
        except ValueError:
            raise ValidationError(f"'{spec.label}' must be a number, got {value!r}") from None
        return format(number, "g")


@register_field_type("date", "Date")
class DateFieldType(FieldType):
    widget = "date_input"
    def normalise_one(self, value: str, spec: FieldSpec) -> str:
        return parse_iso_date(value, spec.label).isoformat()


@register_field_type("boolean", "Yes / No")
class BooleanFieldType(FieldType):
    """Stored as 'yes' or 'no'; blank means "not recorded".

    The form offers blank / Yes / No rather than a checkbox, because a checkbox
    cannot tell "recorded as no" apart from "never filled in", and that
    difference matters for imported historic data."""

    widget = "boolean_input"
    is_countable = True
    TRUE_WORDS = {"yes", "y", "true", "1", "on", "x"}
    FALSE_WORDS = {"no", "n", "false", "0", "off"}

    def normalise_one(self, value: str, spec: FieldSpec) -> str:
        lowered = value.lower()
        if lowered in self.TRUE_WORDS:
            return "yes"
        if lowered in self.FALSE_WORDS:
            return "no"
        raise ValidationError(f"'{spec.label}' must be yes or no, got {value!r}")

    def to_display(self, stored_values: list[str]) -> str:
        return ", ".join(value.capitalize() for value in stored_values)


@register_field_type("choice", "Pick one from a list")
class ChoiceFieldType(FieldType):
    widget = "choice_input"
    uses_choices = True
    is_countable = True

    def normalise_one(self, value: str, spec: FieldSpec) -> str:
        return match_choice(value, spec)


@register_field_type("multi_choice", "Pick any from a list")
class MultiChoiceFieldType(FieldType):
    widget = "multi_choice_input"
    uses_choices = True
    is_multi_valued = True
    is_countable = True

    def to_storage(self, raw_values: list[str], spec: FieldSpec) -> list[str]:
        stored = super().to_storage(raw_values, spec)
        # Keep the order of the choice list and drop duplicates.
        return [choice for choice in spec.choices if choice in stored]

    def normalise_one(self, value: str, spec: FieldSpec) -> str:
        return match_choice(value, spec)


def match_choice(value: str, spec: FieldSpec) -> str:
    """Return the canonical spelling of a choice, matching case-insensitively."""
    for choice in spec.choices:
        if choice.casefold() == value.casefold():
            return choice
    allowed = ", ".join(spec.choices) or "(no choices defined)"
    raise ValidationError(f"'{value}' is not an option for '{spec.label}'. Options: {allowed}")


def parse_iso_date(value: str, label: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(value.strip())
    except ValueError:
        raise ValidationError(f"'{label}' must be a date as YYYY-MM-DD, got {value!r}") from None
