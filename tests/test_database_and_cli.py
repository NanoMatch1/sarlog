import datetime
import sqlite3

import pytest

from sar_log import audit, cli, jobs
from sar_log.database import backup_database, open_database
from sar_log.jobs import JobInput


def test_foreign_keys_are_enforced(connection):
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO job_attendance (job_id, person_id, hours) VALUES (999, 999, 1)")


def test_backup_copies_data_and_prunes_old_copies(tmp_path):
    database_path = tmp_path / "log.sqlite"
    connection = open_database(database_path)
    jobs.create_job(connection, JobInput("E1", "2026-01-01", raw_field_values={"environment": ["Land"]}))
    connection.close()
    backup_directory = tmp_path / "backups"
    for second in range(4):
        backup_path = backup_database(database_path, backup_directory, keep_count=2,
                                      timestamp=datetime.datetime(2026, 1, 1, 0, 0, second))
    assert len(list(backup_directory.glob("*.sqlite"))) == 2
    restored = sqlite3.connect(backup_path)
    assert restored.execute("SELECT event_number FROM job").fetchone()[0] == "E1"


def test_backup_of_missing_database_returns_none(tmp_path):
    assert backup_database(tmp_path / "missing.sqlite", tmp_path / "backups") is None


def test_changes_are_logged(connection):
    job = jobs.create_job(connection, JobInput("E1", "2026-01-01", raw_field_values={"environment": ["Land"]}))
    jobs.delete_job(connection, job.id)
    actions = [change.action for change in audit.list_changes(connection, entity="job")]
    assert actions == ["delete", "create"]


def test_cli_registry_drives_help():
    help_text = cli.build_parser().format_help()
    for name in cli.COMMAND_REGISTRY:
        assert name in help_text


def test_cli_demo_creates_database_and_refuses_to_overwrite(tmp_path, capsys):
    database_path = tmp_path / "demo.sqlite"
    assert cli.main(["--database", str(database_path), "demo"]) == 0
    connection = open_database(database_path)
    assert connection.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 40
    connection.close()
    assert cli.main(["--database", str(database_path), "demo"]) == 1
    assert "Refusing" in capsys.readouterr().out


def test_cli_init_and_backup(tmp_path):
    database_path = tmp_path / "log.sqlite"
    assert cli.main(["--database", str(database_path), "--backups", str(tmp_path / "b"), "init"]) == 0
    assert cli.main(["--database", str(database_path), "--backups", str(tmp_path / "b"), "backup"]) == 0
    assert len(list((tmp_path / "b").glob("*.sqlite"))) == 1
