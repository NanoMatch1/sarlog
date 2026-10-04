from __future__ import annotations

import datetime

import pytest

from sar_log import organisations, people
from sar_log.config import AppConfig
from sar_log.database import open_database
from sar_log.people import PersonInput


@pytest.fixture
def connection(tmp_path):
    database_connection = open_database(tmp_path / "test.sqlite")
    yield database_connection
    database_connection.close()


@pytest.fixture
def home_organisation(connection):
    return organisations.create_organisation(connection, "Home Group")


@pytest.fixture
def make_person(connection):
    def factory(full_name: str, **overrides) -> people.Person:
        return people.create_person(connection, PersonInput(full_name=full_name, **overrides))
    return factory


@pytest.fixture
def app_config(tmp_path) -> AppConfig:
    return AppConfig(database_path=tmp_path / "app.sqlite", backup_directory=tmp_path / "backups")


@pytest.fixture
def as_of() -> datetime.date:
    return datetime.date(2026, 6, 30)
