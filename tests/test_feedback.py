import datetime

import pytest

from sar_log import feedback
from sar_log.errors import ValidationError


def at(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 10, day, 9, 30)


def test_create_list_and_resolve(connection):
    first = feedback.create_feedback(connection, "problem", "  Save button hidden  ", page="/jobs/new",
                                     app_version="0.3.0", created_at=at(1))
    second = feedback.create_feedback(connection, "idea", "Map of jobs", created_at=at(2))
    assert first.message == "Save button hidden" and first.kind_label == "Something isn't working"
    assert [item.id for item in feedback.list_feedback(connection)] == [second.id, first.id]

    feedback.set_feedback_resolved(connection, first.id, True, "fixed in v0.3.1")
    assert [item.id for item in feedback.list_feedback(connection, include_resolved=False)] == [second.id]
    assert feedback.get_feedback(connection, first.id).resolution == "fixed in v0.3.1"
    assert not feedback.set_feedback_resolved(connection, first.id, False).is_resolved


def test_validation(connection):
    with pytest.raises(ValidationError, match="kind"):
        feedback.create_feedback(connection, "complaint", "x")
    with pytest.raises(ValidationError, match="message"):
        feedback.create_feedback(connection, "idea", "   ")


def test_text_for_sending_is_oldest_first_with_context(connection):
    feedback.create_feedback(connection, "idea", "Second", created_at=at(2))
    feedback.create_feedback(connection, "problem", "First", page="/people", app_version="0.3.0", created_at=at(1))
    text = feedback.feedback_as_text(feedback.list_feedback(connection))
    assert text.index("First") < text.index("Second")
    assert "#2 · 2026-10-01 09:30 · Something isn't working\nFirst\n(page /people, version 0.3.0)" in text
