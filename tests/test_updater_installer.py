"""Staging, applying and rolling back updates on a fake install folder."""

import zipfile
from pathlib import Path

import pytest

from release_helpers import make_release_zip, release_files, write_install
from sar_log.updater import installer
from sar_log.updater.installer import InstallLayout, UpdateError
from sar_log.updater.versions import Version, parse_version, read_installed_version

V010, V020 = Version(0, 1, 0), Version(0, 2, 0)


@pytest.fixture
def layout(tmp_path) -> InstallLayout:
    return InstallLayout(write_install(tmp_path / "install", "0.1.0"))


def no_dependency_install(install_directory: Path) -> None:
    raise AssertionError("dependencies should not be reinstalled when pyproject.toml is unchanged")


def stage(layout, tmp_path, version="0.2.0", files=None):
    zip_path = make_release_zip(tmp_path / "zips", version, files)
    installer.stage_release(layout, zip_path, parse_version(version))


def text(layout, relative_path):
    return (layout.install_directory / relative_path).read_text()


def test_stage_unpacks_without_touching_running_code(layout, tmp_path):
    stage(layout, tmp_path)
    assert installer.read_pending(layout) == installer.PendingAction("install", "0.2.0")
    assert read_installed_version(layout.staged_directory) == V020
    assert read_installed_version(layout.install_directory) == V010


def test_apply_swaps_code_and_keeps_data_and_environment(layout, tmp_path):
    stage(layout, tmp_path)
    result = installer.apply_pending(layout, install_dependencies=no_dependency_install)
    assert result.succeeded and "0.1.0 to 0.2.0" in result.message
    assert read_installed_version(layout.install_directory) == V020
    assert text(layout, "sar_log/module.py") == "VERSION_MARKER = '0.2.0'\n"
    assert text(layout, "run_sar_log.bat") == "rem launcher 0.2.0\n"
    assert text(layout, "data/sar_log.sqlite") == "precious records"
    assert text(layout, ".venv/marker") == "environment"
    assert installer.previous_version(layout) == V010
    assert installer.read_pending(layout) is None
    assert not layout.staged_directory.exists()
    assert installer.read_last_result(layout).succeeded


def test_apply_with_nothing_pending_does_nothing(layout):
    assert installer.apply_pending(layout) is None


def test_files_dropped_in_new_release_are_removed_after_a_tracked_update(layout, tmp_path):
    stage(layout, tmp_path, "0.2.0", release_files("0.2.0", {"old_tool.py": "x"}))
    installer.apply_pending(layout, install_dependencies=no_dependency_install)
    assert (layout.install_directory / "old_tool.py").exists()
    stage(layout, tmp_path, "0.3.0")
    installer.apply_pending(layout, install_dependencies=no_dependency_install)
    assert not (layout.install_directory / "old_tool.py").exists()


def test_rollback_restores_previous_and_can_itself_be_undone(layout, tmp_path):
    stage(layout, tmp_path)
    installer.apply_pending(layout, install_dependencies=no_dependency_install)

    assert installer.request_rollback(layout) == V010
    result = installer.apply_pending(layout, install_dependencies=no_dependency_install)
    assert result.succeeded and "Went back" in result.message
    assert read_installed_version(layout.install_directory) == V010
    assert text(layout, "data/sar_log.sqlite") == "precious records"
    assert installer.previous_version(layout) == V020  # going forward again is possible

    installer.request_rollback(layout)
    installer.apply_pending(layout, install_dependencies=no_dependency_install)
    assert read_installed_version(layout.install_directory) == V020


def test_rollback_without_previous_is_refused(layout):
    with pytest.raises(UpdateError, match="no previous version"):
        installer.request_rollback(layout)


def test_changed_pyproject_triggers_dependency_install(layout, tmp_path):
    installed_into = []
    stage(layout, tmp_path, files=release_files("0.2.0", pyproject="[project]\ndependencies = ['new']\n"))
    result = installer.apply_pending(layout, install_dependencies=installed_into.append)
    assert result.succeeded and installed_into == [layout.install_directory]


def test_failed_dependency_install_undoes_the_swap(layout, tmp_path):
    def failing_install(install_directory):
        raise UpdateError("pip exploded")

    stage(layout, tmp_path, files=release_files("0.2.0", pyproject="[project]\ndependencies = ['new']\n"))
    result = installer.apply_pending(layout, install_dependencies=failing_install)
    assert not result.succeeded and "pip exploded" in result.message
    assert read_installed_version(layout.install_directory) == V010
    assert text(layout, "sar_log/module.py") == "VERSION_MARKER = '0.1.0'\n"
    assert installer.read_pending(layout) is None
    assert installer.previous_version(layout) is None


def test_locked_file_part_way_through_undoes_the_swap(layout, tmp_path, monkeypatch):
    """Simulates Windows refusing to move a file that another program has open."""
    stage(layout, tmp_path)
    original_rename = Path.rename
    calls = {"count": 0}

    def flaky_rename(self, target):
        calls["count"] += 1
        if calls["count"] == 3:
            raise PermissionError("file in use")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)
    result = installer.apply_pending(layout, install_dependencies=no_dependency_install)
    monkeypatch.setattr(Path, "rename", original_rename)

    assert not result.succeeded and "another copy" in result.message
    assert read_installed_version(layout.install_directory) == V010
    for relative_path in release_files("0.1.0"):
        assert (layout.install_directory / relative_path).exists(), relative_path
    assert text(layout, "data/sar_log.sqlite") == "precious records"


def test_wrong_version_in_archive_is_rejected(layout, tmp_path):
    zip_path = make_release_zip(tmp_path / "zips", "0.2.0", release_files("0.3.0"))
    with pytest.raises(UpdateError, match="expected 0.2.0"):
        installer.stage_release(layout, zip_path, V020)
    assert installer.read_pending(layout) is None


def test_archive_with_path_traversal_is_rejected(layout, tmp_path):
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("sarlog-0.2.0/sar_log/__init__.py", '__version__ = "0.2.0"\n')
        archive.writestr("sarlog-0.2.0/../../escaped.txt", "x")
    with pytest.raises(UpdateError, match="unsafe path"):
        installer.stage_release(layout, zip_path, V020)
    assert not (tmp_path / "escaped.txt").exists()


def test_archive_cannot_overwrite_protected_folders(layout, tmp_path):
    stage(layout, tmp_path, files=release_files("0.2.0", {"data/sar_log.sqlite": "overwritten!"}))
    installer.apply_pending(layout, install_dependencies=no_dependency_install)
    assert text(layout, "data/sar_log.sqlite") == "precious records"


def test_not_a_zip_is_rejected(layout, tmp_path):
    bad_path = tmp_path / "bad.zip"
    bad_path.write_text("not a zip")
    with pytest.raises(UpdateError, match="not a valid"):
        installer.stage_release(layout, bad_path, V020)


def test_git_checkout_refuses_updates(layout, tmp_path):
    (layout.install_directory / ".git").mkdir()
    with pytest.raises(UpdateError, match="git"):
        stage(layout, tmp_path)


def test_cancel_clears_staged_update(layout, tmp_path):
    stage(layout, tmp_path)
    installer.clear_pending(layout)
    assert installer.read_pending(layout) is None and not layout.staged_directory.exists()
    assert installer.apply_pending(layout) is None
