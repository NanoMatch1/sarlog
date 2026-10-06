import sqlite3

import pytest

from release_helpers import make_release_zip, write_install
from sar_log import launcher
from sar_log.database import (MIGRATIONS, DatabaseTooNewError, Migration, apply_migrations, connect,
                              initialise, latest_schema_version, open_database, read_schema_version)
from sar_log.updater import installer
from sar_log.updater.installer import InstallLayout
from sar_log.updater.versions import Version, read_installed_version


# ---------------------------------------------------------------- launcher

@pytest.fixture
def not_running(monkeypatch):
    monkeypatch.setattr(launcher, "app_already_running", lambda address: False)


def scripted_server(exit_codes, seen_arguments):
    def run_server(arguments):
        seen_arguments.append(arguments)
        return exit_codes.pop(0)
    return run_server


def test_launcher_applies_pending_update_then_restarts_on_request(tmp_path, not_running):
    layout = InstallLayout(write_install(tmp_path / "install", "0.1.0"))
    installer.stage_release(layout, make_release_zip(tmp_path / "zips", "0.2.0"), Version(0, 2, 0))
    seen = []

    def run_server(arguments):
        seen.append((arguments, read_installed_version(layout.install_directory)))
        if len(seen) == 1:
            # The user installs 0.3.0 from the Updates page, then clicks Restart.
            installer.stage_release(layout, make_release_zip(tmp_path / "zips", "0.3.0"), Version(0, 3, 0))
            return launcher.RESTART_EXIT_CODE
        return 0

    exit_code = launcher.run_launcher(layout.install_directory, ["serve"], "http://127.0.0.1:1/",
                                      run_server=run_server, install_dependencies=lambda path: None)
    assert exit_code == 0
    assert seen == [(["serve"], Version(0, 2, 0)), (["serve", "--no-browser"], Version(0, 3, 0))]


def test_launcher_returns_to_newer_version_when_database_is_too_new(tmp_path, not_running):
    layout = InstallLayout(write_install(tmp_path / "install", "0.1.0"))
    installer.stage_release(layout, make_release_zip(tmp_path / "zips", "0.2.0"), Version(0, 2, 0))
    installer.apply_pending(layout, install_dependencies=lambda path: None)
    installer.request_rollback(layout)  # user goes back to 0.1.0, but 0.2.0 migrated the database
    seen = []
    exit_codes = [launcher.DATABASE_TOO_NEW_EXIT_CODE, 0]

    def run_server(arguments):
        seen.append(read_installed_version(layout.install_directory))
        return exit_codes.pop(0)

    launcher.run_launcher(layout.install_directory, ["serve"], "http://127.0.0.1:1/",
                          run_server=run_server, install_dependencies=lambda path: None)
    assert seen == [Version(0, 1, 0), Version(0, 2, 0)]


def test_launcher_stops_on_other_exit_codes(tmp_path, not_running):
    seen = []
    exit_code = launcher.run_launcher(tmp_path, ["serve"], "http://127.0.0.1:1/",
                                      run_server=scripted_server([1], seen))
    assert exit_code == 1 and len(seen) == 1


def test_launcher_only_opens_browser_when_already_running(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "app_already_running", lambda address: True)
    opened = []
    assert launcher.run_launcher(tmp_path, ["serve"], "http://127.0.0.1:1/", run_server=None,
                                 open_browser=opened.append) == 0
    assert opened == ["http://127.0.0.1:1/"]


def test_app_already_running_is_false_when_nothing_listens():
    assert not launcher.app_already_running("http://127.0.0.1:9/")


# ---------------------------------------------------------------- migrations

# A hypothetical next release's migration, on top of the real ones.
NEXT_VERSION = latest_schema_version() + 1
ADD_RADIO_CHANNEL = Migration(NEXT_VERSION, "add radio channel to job",
                              lambda connection: connection.execute(
                                  "ALTER TABLE job ADD COLUMN radio_channel TEXT NOT NULL DEFAULT ''"))
WITH_RADIO_CHANNEL = (*MIGRATIONS, ADD_RADIO_CHANNEL)


def column_names(connection, table):
    return [row["name"] for row in connection.execute(f"PRAGMA table_info({table})")]


def test_new_database_starts_at_latest_version_without_running_migrations(tmp_path):
    connection = connect(tmp_path / "new.sqlite")
    initialise(connection, migrations=(*MIGRATIONS, Migration(NEXT_VERSION, "would fail", lambda c: 1 / 0)))
    assert read_schema_version(connection) == NEXT_VERSION


def test_existing_database_is_migrated_once(tmp_path):
    connection = open_database(tmp_path / "old.sqlite")  # made by the current release
    connection.execute("INSERT INTO job (event_number, start_date, created_at, updated_at) "
                       "VALUES ('E1', '2026-01-01', 'now', 'now')")
    connection.commit()
    initialise(connection, migrations=WITH_RADIO_CHANNEL)
    assert read_schema_version(connection) == NEXT_VERSION
    assert "radio_channel" in column_names(connection, "job")
    assert connection.execute("SELECT event_number FROM job").fetchone()[0] == "E1"
    assert apply_migrations(connection, WITH_RADIO_CHANNEL) == []


def test_failed_migration_leaves_database_at_last_good_version(tmp_path):
    connection = open_database(tmp_path / "old.sqlite")

    def broken(connection):
        connection.execute("ALTER TABLE job ADD COLUMN half_done TEXT")
        raise sqlite3.OperationalError("boom")

    with pytest.raises(sqlite3.OperationalError):
        apply_migrations(connection, (*MIGRATIONS, Migration(NEXT_VERSION, "broken", broken)))
    assert read_schema_version(connection) == latest_schema_version()
    assert "half_done" not in column_names(connection, "job")


def test_older_code_refuses_newer_database(tmp_path):
    connection = connect(tmp_path / "db.sqlite")
    initialise(connection, migrations=WITH_RADIO_CHANNEL)
    with pytest.raises(DatabaseTooNewError, match="restore a backup"):
        initialise(connection, migrations=MIGRATIONS)


def make_version_1_database(path):
    """A database as v0.1.x/v0.2.x left it: no feedback table, schema version 1."""
    connection = open_database(path)
    connection.execute("DROP TABLE feedback")
    connection.execute("UPDATE schema_info SET value = '1' WHERE key = 'schema_version'")
    connection.commit()
    connection.close()


def test_version_1_database_gains_feedback_table(tmp_path):
    make_version_1_database(tmp_path / "v1.sqlite")
    connection = open_database(tmp_path / "v1.sqlite")
    assert read_schema_version(connection) == 2
    assert "message" in column_names(connection, "feedback")
