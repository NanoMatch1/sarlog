"""Small date helpers. All dates are stored as ISO text (YYYY-MM-DD)."""

from __future__ import annotations

import calendar
import datetime

from sar_log.errors import ValidationError


def parse_optional_date(value: str | None, label: str) -> str | None:
    """Return a normalised ISO date string, or None for blank input."""
    if value is None or not str(value).strip():
        return None
    try:
        return datetime.date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise ValidationError(f"'{label}' must be a date as YYYY-MM-DD, got {value!r}") from None


def parse_required_date(value: str | None, label: str) -> str:
    parsed = parse_optional_date(value, label)
    if parsed is None:
        raise ValidationError(f"'{label}' is required")
    return parsed


def add_months(start: datetime.date, months: int) -> datetime.date:
    """Add (or subtract) calendar months, clamping to the end of short months."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def today() -> datetime.date:
    return datetime.date.today()
