"""Command line: ``python -m sar_log <command>``.

Commands register themselves with ``@command``; the registry drives both
dispatch and ``--help`` text.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sar_log.config import AppConfig, DEFAULT_BACKUP_DIRECTORY, DEFAULT_DATABASE_PATH, DEFAULT_HOST, DEFAULT_PORT
from sar_log.database import backup_database, open_database


@dataclass(frozen=True)
class Command:
    name: str
    help_text: str
    add_arguments: Callable[[argparse.ArgumentParser], None]
    run: Callable[[argparse.Namespace, AppConfig], int]


COMMAND_REGISTRY: dict[str, Command] = {}


def command(name: str, help_text: str, add_arguments: Callable[[argparse.ArgumentParser], None] = lambda parser: None):
    def decorator(run: Callable[[argparse.Namespace, AppConfig], int]):
        COMMAND_REGISTRY[name] = Command(name, help_text, add_arguments, run)
        return run
    return decorator


def _serve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")


@command("serve", "Back up the database, then start the app at http://127.0.0.1:<port>", _serve_arguments)
def serve(arguments: argparse.Namespace, config: AppConfig) -> int:
    from waitress import serve as waitress_serve

    from sar_log.web import create_app

    backup_path = backup_database(config.database_path, config.backup_directory, config.backup_keep_count)
    if backup_path:
        print(f"Backup written: {backup_path}")
    config = AppConfig(**{**config.__dict__, "port": arguments.port})
    app = create_app(config)
    address = f"http://{config.host}:{config.port}/"
    print(f"SAR Log running at {address}  (database: {config.database_path})")
    print("Close this window or press Ctrl+C to stop.")
    if not arguments.no_browser:
        webbrowser.open(address)
    waitress_serve(app, host=config.host, port=config.port)
    return 0


@command("init", "Create an empty database (does nothing if it already exists)")
def init(arguments: argparse.Namespace, config: AppConfig) -> int:
    open_database(config.database_path).close()
    print(f"Database ready: {config.database_path}")
    return 0


@command("backup", "Write a timestamped backup copy of the database")
def backup(arguments: argparse.Namespace, config: AppConfig) -> int:
    backup_path = backup_database(config.database_path, config.backup_directory, config.backup_keep_count)
    print(f"Backup written: {backup_path}" if backup_path else "No database to back up yet.")
    return 0


@command("demo", "Fill a NEW database with made-up data for trying the app (refuses an existing file)")
def demo(arguments: argparse.Namespace, config: AppConfig) -> int:
    from sar_log.demo_data import populate_demo_data

    if Path(config.database_path).exists():
        print(f"Refusing: {config.database_path} already exists. Pass --database with a new file name.")
        return 1
    connection = open_database(config.database_path)
    populate_demo_data(connection)
    connection.close()
    print(f"Demo database written: {config.database_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sar_log", description="SAR job and training log")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH,
                        help=f"database file (default: {DEFAULT_DATABASE_PATH})")
    parser.add_argument("--backups", type=Path, default=DEFAULT_BACKUP_DIRECTORY,
                        help=f"backup folder (default: {DEFAULT_BACKUP_DIRECTORY})")
    subparsers = parser.add_subparsers(dest="command_name", required=True)
    for registered in COMMAND_REGISTRY.values():
        registered.add_arguments(subparsers.add_parser(registered.name, help=registered.help_text))
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    config = AppConfig(database_path=arguments.database, backup_directory=arguments.backups, host=DEFAULT_HOST)
    return COMMAND_REGISTRY[arguments.command_name].run(arguments, config)


if __name__ == "__main__":
    sys.exit(main())
