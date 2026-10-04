"""Where releases come from.

Every source offers the same three calls, so the update page and installer do
not care whether releases come from GitHub or a local folder:

* ``list_releases()`` -> releases, newest first
* ``changelog_text(release)`` -> CHANGELOG.md as of that release ('' if none)
* ``download(release, destination)`` -> path of the downloaded zip

``GitHubTagSource`` is the real one. ``DirectorySource`` reads zips from a
folder; it is the simulation mode used by tests and for trying an update
without touching GitHub.
"""

from __future__ import annotations

import json
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from sar_log.updater.versions import Version, parse_version

HTTP_TIMEOUT_SECONDS = 20


class UpdateSourceError(Exception):
    """A source could not be reached or returned something unusable."""


@dataclass(frozen=True)
class Release:
    version: Version
    download_location: str  # URL or file path, interpreted by the source


class UpdateSource(Protocol):
    description: str

    def list_releases(self) -> list[Release]: ...

    def changelog_text(self, release: Release) -> str: ...

    def download(self, release: Release, destination: Path) -> Path: ...


def latest_release(source: UpdateSource) -> Release | None:
    releases = source.list_releases()
    return releases[0] if releases else None


def find_release(source: UpdateSource, version: Version) -> Release:
    for release in source.list_releases():
        if release.version == version:
            return release
    raise UpdateSourceError(f"Version {version} is not available from {source.description}")


# ---------------------------------------------------------------- GitHub

def urllib_get(url: str) -> bytes:
    """Fetch a URL. GitHub's API requires a User-Agent header."""
    request = urllib.request.Request(url, headers={"User-Agent": "sar-log-updater"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.read()
    except OSError as error:  # URLError, HTTPError and timeouts are all OSErrors
        raise UpdateSourceError(f"Could not reach {url}: {error}") from error


class GitHubTagSource:
    """Releases are the repository's tags named vX.Y.Z. Works anonymously for a
    public repository; the only information sent to GitHub is the request itself."""

    def __init__(self, repository: str, http_get: Callable[[str], bytes] = urllib_get):
        self.repository = repository  # "owner/name"
        self.http_get = http_get
        self.description = f"github.com/{repository}"

    def list_releases(self) -> list[Release]:
        payload = self.http_get(f"https://api.github.com/repos/{self.repository}/tags?per_page=100")
        try:
            tags = json.loads(payload)
            names = [tag["name"] for tag in tags]
        except (ValueError, TypeError, KeyError) as error:
            raise UpdateSourceError("GitHub returned an unexpected list of versions") from error
        releases = []
        for name in names:
            version = parse_version(name)
            if version is not None:
                releases.append(Release(
                    version,
                    f"https://codeload.github.com/{self.repository}/zip/refs/tags/{version.tag}"))
        return sorted(releases, key=lambda release: release.version, reverse=True)

    def changelog_text(self, release: Release) -> str:
        url = f"https://raw.githubusercontent.com/{self.repository}/{release.version.tag}/CHANGELOG.md"
        try:
            return self.http_get(url).decode("utf-8")
        except UpdateSourceError:
            return ""

    def download(self, release: Release, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.http_get(release.download_location))
        return destination


# ---------------------------------------------------------------- simulation

class DirectorySource:
    """Releases are files named vX.Y.Z.zip in a folder, laid out like GitHub's
    zips (one top-level folder containing the repository)."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.description = f"folder {self.directory}"

    def list_releases(self) -> list[Release]:
        if not self.directory.is_dir():
            raise UpdateSourceError(f"Update folder {self.directory} does not exist")
        releases = []
        for zip_path in self.directory.glob("*.zip"):
            version = parse_version(zip_path.stem)
            if version is not None:
                releases.append(Release(version, str(zip_path)))
        return sorted(releases, key=lambda release: release.version, reverse=True)

    def changelog_text(self, release: Release) -> str:
        with zipfile.ZipFile(release.download_location) as archive:
            for name in archive.namelist():
                if name.count("/") == 1 and name.endswith("/CHANGELOG.md"):
                    return archive.read(name).decode("utf-8")
        return ""

    def download(self, release: Release, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(release.download_location, destination)
        return destination
