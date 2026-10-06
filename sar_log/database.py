"""Opening, initialising and backing up the SQLite database file."""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable

from sar_log import default_fields


@dataclass(frozen=True)
class Migration:
    """One step that upgrades an existing database by one schema version.

    schema.sql always describes the *latest* schema, so a brand-new database
    is created at the latest version and never runs migrations. Migrations
    exist only to bring older databases (from an earlier release) up to date.
    """

    version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


def _add_feedback_table(connection: sqlite3.Connection) -> None:
    # A single execute, not executescript: executescript commits first, which
    # would break the migration's all-or-nothing transaction.
    connection.execute("""
        CREATE TABLE feedback (
            id          INTEGER PRIMARY KEY,
            created_at  TEXT NOT NULL,
            kind        TEXT NOT NULL,
            message     TEXT NOT NULL,
            page        TEXT NOT NULL DEFAULT '',
            app_version TEXT NOT NULL DEFAULT '',
            is_resolved INTEGER NOT NULL DEFAULT 0,
            resolution  TEXT NOT NULL DEFAULT ''
        )""")


# Ordered list of migrations. Adding one is a single entry here plus the
# matching change to schema.sql. The first schema is version 1. Migrations
# are frozen once released: they describe how the schema *was* changed.
MIGRATIONS: tuple[Migration, ...] = (
    Migration(2, "add feedback table (v0.3.0)", _add_feedback_table),
)


class DatabaseTooNewError(RuntimeError):
    """The database was upgraded by a newer version of the app than this one."""


def latest_schema_version(migrations: tuple[Migration, ...] = MIGRATIONS) -> int:
    return max([1, *(migration.version for migration in migrations)])


def read_schema_version(connection: sqlite3.Connection) -> int | None:
    has_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_info'").fetchone()
    if not has_table:
        return None
    row = connection.execute("SELECT value FROM schema_info WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else None


def apply_migrations(connection: sqlite3.Connection, migrations: tuple[Migration, ...] = MIGRATIONS) -> list[int]:
    """Upgrade the database in place; return the versions applied.

    Each migration runs in its own transaction together with the version
    bump, so a failure leaves the database at the last good version.
    """
    current_version = read_schema_version(connection) or 1
    latest_version = latest_schema_version(migrations)
    if current_version > latest_version:
        raise DatabaseTooNewError(
            f"This database is at schema version {current_version}, but this version of SAR Log "
            f"only understands up to {latest_version}. Update the app, or restore a backup "
            f"from data/backups made before the newer version was used.")
    applied = []
    for migration in sorted(migrations, key=lambda migration: migration.version):
        if migration.version <= current_version:
            continue
        # Explicit BEGIN: Python's sqlite3 does not wrap schema changes such as
        # ALTER TABLE in a transaction by itself, so a half-applied migration
        # could otherwise survive a failure.
        connection.commit()
        connection.execute("BEGIN")
        try:
            migration.apply(connection)
            connection.execute("UPDATE schema_info SET value = ? WHERE key = 'schema_version'",
                               (str(migration.version),))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        applied.append(migration.version)
    return applied


def connect(database_path: Path | str) -> sqlite3.Connection:
    """Open a connection with the settings every part of the app relies on."""
    connection = sqlite3.connect(str(database_path), detect_types=0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialise(connection: sqlite3.Connection, migrations: tuple[Migration, ...] = MIGRATIONS) -> None:
    """Create or upgrade the schema and seed default fields. Safe to run repeatedly."""
    is_new_database = read_schema_version(connection) is None
    if not is_new_database:
        apply_migrations(connection, migrations)
    schema_sql = resources.files("sar_log").joinpath("schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema_sql)
    if is_new_database:
        connection.execute("INSERT INTO schema_info (key, value) VALUES ('schema_version', ?)",
                           (str(latest_schema_version(migrations)),))
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
