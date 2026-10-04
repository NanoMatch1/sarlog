"""Opening, initialising and backing up the SQLite database file."""

from __future__ import annotations

import datetime
import sqlite3
from importlib import resources
from pathlib import Path

from sar_log import default_fields

SCHEMA_VERSION = "1"


def connect(database_path: Path | str) -> sqlite3.Connection:
    """Open a connection with the settings every part of the app relies on."""
    connection = sqlite3.connect(str(database_path), detect_types=0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialise(connection: sqlite3.Connection) -> None:
    """Create tables and seed default field definitions. Safe to run repeatedly."""
    schema_sql = resources.files("sar_log").joinpath("schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema_sql)
    connection.execute(
        "INSERT OR IGNORE INTO schema_info (key, value) VALUES ('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    default_fields.seed_default_fields(connection)
    connection.commit()


def open_database(database_path: Path | str) -> sqlite3.Connection:
    """Connect to a database file, creating and initialising it if needed."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    initialise(connection)
    return connection


def backup_database(
    database_path: Path | str,
    backup_directory: Path | str,
    keep_count: int = 30,
    timestamp: datetime.datetime | None = None,
) -> Path | None:
    """Copy the database to a timestamped file and prune old copies.

    Uses SQLite's online backup API, which gives a consistent copy even while
    the app has the file open. Returns the new backup path, or None when there
    is no database yet.
    """
    source_path = Path(database_path)
    if not source_path.exists():
        return None
    target_directory = Path(backup_directory)
    target_directory.mkdir(parents=True, exist_ok=True)
    stamp = (timestamp or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
    target_path = target_directory / f"{source_path.stem}_{stamp}.sqlite"

    source_connection = sqlite3.connect(str(source_path))
    target_connection = sqlite3.connect(str(target_path))
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()

    existing_backups = sorted(target_directory.glob(f"{source_path.stem}_*.sqlite"))
    for old_backup in existing_backups[:-keep_count]:
        old_backup.unlink()
    return target_path
