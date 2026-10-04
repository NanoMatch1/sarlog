"""Reading release notes from CHANGELOG.md.

Each release has a section headed ``## vX.Y.Z`` (anything after the version on
that line, such as a date, is ignored). The update page shows the sections
newer than the installed version.
"""

from __future__ import annotations

import re

from sar_log.updater.versions import Version, parse_version

_HEADING_PATTERN = re.compile(r"^##\s+(v?\d+\.\d+\.\d+)\b.*$", re.MULTILINE)


def parse_changelog(changelog_text: str) -> dict[Version, str]:
    """Map each version to the text of its section."""
    headings = list(_HEADING_PATTERN.finditer(changelog_text))
    sections: dict[Version, str] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog_text)
        version = parse_version(heading.group(1))
        if version is not None:
            sections[version] = changelog_text[heading.end():end].strip()
    return sections


def notes_newer_than(changelog_text: str, installed: Version | None) -> list[tuple[Version, str]]:
    """Sections for versions after ``installed``, newest first."""
    sections = parse_changelog(changelog_text)
    return sorted(((version, notes) for version, notes in sections.items()
                   if installed is None or version > installed), reverse=True)
