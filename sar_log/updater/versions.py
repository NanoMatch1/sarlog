"""Version numbers of the form MAJOR.MINOR.PATCH, tagged in git as vMAJOR.MINOR.PATCH."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_VERSION_ASSIGNMENT_PATTERN = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def tag(self) -> str:
        return f"v{self}"


def parse_version(text: str) -> Version | None:
    """Parse '1.2.3' or 'v1.2.3'; anything else (e.g. 'v1.2-beta') gives None."""
    match = _VERSION_PATTERN.match(text.strip())
    return Version(*(int(part) for part in match.groups())) if match else None


def read_installed_version(install_directory: Path) -> Version | None:
    """Read the version from source text rather than importing it, so the
    answer reflects the files on disk, not whatever is already in memory."""
    init_path = Path(install_directory) / "sar_log" / "__init__.py"
    if not init_path.exists():
        return None
    match = _VERSION_ASSIGNMENT_PATTERN.search(init_path.read_text(encoding="utf-8"))
    return parse_version(match.group(1)) if match else None
