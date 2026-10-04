"""Application configuration, passed explicitly into the app and the CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sar_log.updater.sources import DirectorySource, GitHubTagSource, UpdateSource

PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = PROJECT_DIRECTORY / "data" / "sar_log.sqlite"
DEFAULT_BACKUP_DIRECTORY = PROJECT_DIRECTORY / "data" / "backups"

# Localhost only: the data includes personal and health details, so the app
# must not be reachable from other machines unless deliberately configured.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

UPDATE_REPOSITORY = "NanoMatch1/sarlog"


@dataclass(frozen=True)
class AppConfig:
    database_path: Path = DEFAULT_DATABASE_PATH
    backup_directory: Path = DEFAULT_BACKUP_DIRECTORY
    backup_keep_count: int = 30
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    # Folder the app is installed in; updates replace code here (never data/).
    install_directory: Path = PROJECT_DIRECTORY
    update_repository: str = UPDATE_REPOSITORY
    # Simulation mode: take releases from a folder of vX.Y.Z.zip files instead of GitHub.
    update_source_directory: Path | None = None
    # Look for a newer release once in the background when the app starts.
    check_for_updates_on_start: bool = True
    # Training thresholds used by the training overview page.
    training_period_months: int = 12
    training_lapse_months: int = 12


def make_update_source(config: AppConfig) -> UpdateSource:
    if config.update_source_directory is not None:
        return DirectorySource(config.update_source_directory)
    return GitHubTagSource(config.update_repository)
