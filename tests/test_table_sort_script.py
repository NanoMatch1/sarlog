"""Runs the browser's table-sorting logic (static/table_sort.js) in QuickJS.

The DOM wiring is checked by hand in a browser; the ordering rules, which
are what users notice, are checked here.
"""

import json
from pathlib import Path

import pytest

quickjs = pytest.importorskip("quickjs")

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "sar_log/web/static/table_sort.js"


@pytest.fixture(scope="module")
def sorted_values():
    context = quickjs.Context()
    context.eval(SCRIPT_PATH.read_text(encoding="utf-8"))

    def sort(values, descending=False):
        indices = json.loads(context.eval(
            f"JSON.stringify(SarTableSort.sortedOrder({json.dumps(values)}, {json.dumps(descending)}))"))
        return [values[index] for index in indices]
    return sort


def test_numbers_sort_numerically(sorted_values):
    assert sorted_values(["10", "9", "1,200", "2.5"]) == ["2.5", "9", "10", "1,200"]
    assert sorted_values(["45%", "100%", "5%"], descending=True) == ["100%", "45%", "5%"]


def test_text_sorts_naturally_ignoring_case(sorted_values):
    assert sorted_values(["E10", "e9", "E100", "D200"]) == ["D200", "e9", "E10", "E100"]
    assert sorted_values(["bob", "Alice", "carol"]) == ["Alice", "bob", "carol"]


def test_iso_dates_sort_chronologically(sorted_values):
    assert sorted_values(["2026-01-05", "2025-12-31", "2026-01-04"], descending=True) == \
        ["2026-01-05", "2026-01-04", "2025-12-31"]


def test_blanks_go_last_in_both_directions(sorted_values):
    assert sorted_values(["b", "", "a", "—"]) == ["a", "b", "", "—"]
    assert sorted_values(["b", "", "a"], descending=True) == ["b", "a", ""]


def test_ties_keep_their_original_order(sorted_values):
    assert sorted_values(["x", "X", "x "]) == ["x", "X", "x "]
