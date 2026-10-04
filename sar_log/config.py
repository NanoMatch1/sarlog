"""Application configuration, passed explicitly into the app and the CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = PROJECT_DIRECTORY / "data" / "sar_log.sqlite"
DEFAULT_BACKUP_DIRECTORY = PROJECT_DIRECTORY / "data" / "backups"

# Localhost only: the data includes personal and health details, so the app
# must not be reachable from other machines unless deliberately configured.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


@dataclass(frozen=True)
class AppConfig:
    database_path: Path = DEFAULT_DATABASE_PATH
    backup_directory: Path = DEFAULT_BACKUP_DIRECTORY
    backup_keep_count: int = 30
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    # Training thresholds used by the training overview page.
    training_period_months: int = 12
    training_lapse_months: int = 12
