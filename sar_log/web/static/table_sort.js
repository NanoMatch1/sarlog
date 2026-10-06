// Click a column heading of any <table class="sortable"> to sort its rows by
// that column; click again to reverse. Runs entirely in the browser, so the
// sort order is not saved and nothing is sent anywhere.
//
// A cell sorts by its data-sort-value attribute when it has one (use this
// when the shown text is not what should be compared, e.g. "never" for a
// missing date), otherwise by its visible text. Numbers compare as numbers,
// everything else (names, event numbers, YYYY-MM-DD dates) in natural order,
// so "E9" comes before "E10". Blank cells always go last.

(function (root) {
  "use strict";

  var BLANK_VALUES = ["", "—", "-"];

  function parseNumber(text) {
    var cleaned = text.replace(/[,%\s]/g, "");
    if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(cleaned)) return null;
    return Number(cleaned);
  }

  // Natural order: runs of digits compare as numbers, other text ignoring
  // case. Written out rather than using localeCompare options, which not
  // every JavaScript engine honours.
  function compareNaturally(left, right) {
    var leftParts = left.toLowerCase().match(/\d+|\D+/g) || [];
    var rightParts = right.toLowerCase().match(/\d+|\D+/g) || [];
    for (var index = 0; index < Math.min(leftParts.length, rightParts.length); index++) {
      var leftPart = leftParts[index];
      var rightPart = rightParts[index];
      var bothDigits = /^\d/.test(leftPart) && /^\d/.test(rightPart);
      var difference = bothDigits ? Number(leftPart) - Number(rightPart)
        : (leftPart < rightPart ? -1 : leftPart > rightPart ? 1 : 0);
      if (difference) return difference;
    }
    return leftParts.length - rightParts.length;
  }

  function compareSortValues(left, right) {
    var leftNumber = parseNumber(left);
    var rightNumber = parseNumber(right);
    if (leftNumber !== null && rightNumber !== null) return leftNumber - rightNumber;
    return compareNaturally(left, right);
  }

  // Pure ordering step, kept separate from the page so it can be tested:
  // returns the indices of `values` in sorted order, blanks last, ties kept
  // in their original order.
  function sortedOrder(values, descending) {
    var indices = values.map(function (_, index) { return index; });
    var direction = descending ? -1 : 1;
    indices.sort(function (leftIndex, rightIndex) {
      var leftBlank = BLANK_VALUES.indexOf(values[leftIndex].trim()) !== -1;
      var rightBlank = BLANK_VALUES.indexOf(values[rightIndex].trim()) !== -1;
      if (leftBlank !== rightBlank) return leftBlank ? 1 : -1;
      var comparison = leftBlank ? 0 : direction * compareSortValues(values[leftIndex].trim(), values[rightIndex].trim());
      return comparison || leftIndex - rightIndex;
    });
    return indices;
  }

  function cellSortValue(row, columnIndex) {
    var cell = row.cells[columnIndex];
    if (!cell) return "";
    var explicitValue = cell.getAttribute("data-sort-value");
    return explicitValue !== null ? explicitValue : cell.textContent;
  }

  function sortTableByColumn(table, heading, columnIndex) {
    var descending = heading.getAttribute("aria-sort") === "ascending";
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (otherHeading) {
      otherHeading.removeAttribute("aria-sort");
    });
    heading.setAttribute("aria-sort", descending ? "descending" : "ascending");
    Array.prototype.forEach.call(table.tBodies, function (body) {
      var rows = Array.prototype.slice.call(body.rows);
      if (rows.length < 2) return;
      var values = rows.map(function (row) { return cellSortValue(row, columnIndex); });
      sortedOrder(values, descending).forEach(function (rowIndex) { body.appendChild(rows[rowIndex]); });
    });
  }

  function makeSortable(table) {
    if (!table.tHead || !table.tHead.rows.length) return;
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (heading, columnIndex) {
      if (!heading.textContent.trim()) return;  // e.g. a column of buttons
      heading.classList.add("sort-heading");
      heading.tabIndex = 0;
      heading.title = "Click to sort";
      heading.addEventListener("click", function () { sortTableByColumn(table, heading, columnIndex); });
      heading.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          sortTableByColumn(table, heading, columnIndex);
        }
      });
    });
  }

  root.SarTableSort = { compareSortValues: compareSortValues, sortedOrder: sortedOrder };

  if (root.document) {
    root.document.addEventListener("DOMContentLoaded", function () {
      Array.prototype.forEach.call(root.document.querySelectorAll("table.sortable"), makeSortable);
    });
  }
})(this);
