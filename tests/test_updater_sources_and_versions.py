import json
import re
from pathlib import Path

import pytest

import sar_log
from release_helpers import make_release_zip
from sar_log.updater.changelog import notes_newer_than, parse_changelog
from sar_log.updater.sources import (DirectorySource, GitHubTagSource, UpdateSourceError, find_release,
                                     latest_release)
from sar_log.updater.versions import Version, parse_version

PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent


def test_parse_version():
    assert parse_version("v1.2.3") == Version(1, 2, 3)
    assert parse_version("0.10.0") > parse_version("0.9.9")
    assert parse_version("v1.2-beta") is None
    assert Version(0, 2, 0).tag == "v0.2.0"


def test_changelog_sections_and_newer_notes():
    text = "# Changelog\n\n## v0.3.0 — date\n- three\n\n## v0.2.0\n- two\n\n## v0.1.0\n- one\n"
    assert parse_changelog(text)[Version(0, 2, 0)] == "- two"
    assert [str(version) for version, _ in notes_newer_than(text, Version(0, 1, 0))] == ["0.3.0", "0.2.0"]
    assert notes_newer_than(text, Version(0, 3, 0)) == []


def test_release_discipline_changelog_has_running_version():
    """A release without user-facing notes should not happen."""
    changelog = (PROJECT_DIRECTORY / "CHANGELOG.md").read_text(encoding="utf-8")
    assert parse_version(sar_log.__version__) in parse_changelog(changelog)


def test_pyproject_reads_version_from_package():
    assert re.search(r'version = \{attr = "sar_log.__version__"\}',
                     (PROJECT_DIRECTORY / "pyproject.toml").read_text())


class FakeGitHub:
    def __init__(self, tags, files=None, fail=False):
        self.tags, self.files, self.fail, self.requested = tags, files or {}, fail, []

    def __call__(self, url: str) -> bytes:
        self.requested.append(url)
        if self.fail:
            raise UpdateSourceError("offline")
        if url.startswith("https://api.github.com/"):
            return json.dumps([{"name": name} for name in self.tags]).encode()
        if url in self.files:
            return self.files[url]
        raise UpdateSourceError("404")


def test_github_source_lists_version_tags_newest_first_and_ignores_others():
    source = GitHubTagSource("owner/repo", http_get=FakeGitHub(["v0.1.0", "v0.10.0", "v0.2.0", "test-tag"]))
    assert [str(release.version) for release in source.list_releases()] == ["0.10.0", "0.2.0", "0.1.0"]
    release = latest_release(source)
    assert release.download_location == "https://codeload.github.com/owner/repo/zip/refs/tags/v0.10.0"


def test_github_source_changelog_and_download(tmp_path):
    changelog_url = "https://raw.githubusercontent.com/owner/repo/v0.2.0/CHANGELOG.md"
    zip_url = "https://codeload.github.com/owner/repo/zip/refs/tags/v0.2.0"
    fake = FakeGitHub(["v0.2.0"], {changelog_url: b"## v0.2.0\n- new", zip_url: b"zipbytes"})
    source = GitHubTagSource("owner/repo", http_get=fake)
    release = find_release(source, Version(0, 2, 0))
    assert source.changelog_text(release) == "## v0.2.0\n- new"
    assert source.download(release, tmp_path / "d" / "v.zip").read_bytes() == b"zipbytes"


def test_github_source_errors():
    with pytest.raises(UpdateSourceError):
        GitHubTagSource("o/r", http_get=FakeGitHub([], fail=True)).list_releases()
    with pytest.raises(UpdateSourceError, match="unexpected"):
        GitHubTagSource("o/r", http_get=lambda url: b"{not json").list_releases()
    with pytest.raises(UpdateSourceError, match="not available"):
        find_release(GitHubTagSource("o/r", http_get=FakeGitHub(["v0.1.0"])), Version(9, 9, 9))


def test_directory_source(tmp_path):
    make_release_zip(tmp_path, "0.2.0")
    make_release_zip(tmp_path, "0.3.0")
    (tmp_path / "notes.zip").write_text("ignored: not a version name")
    source = DirectorySource(tmp_path)
    release = latest_release(source)
    assert release.version == Version(0, 3, 0)
    assert "Notes for 0.3.0" in source.changelog_text(release)
    assert source.download(release, tmp_path / "out" / "x.zip").exists()
    with pytest.raises(UpdateSourceError):
        DirectorySource(tmp_path / "missing").list_releases()
