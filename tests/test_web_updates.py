"""Headless workflow for the Updates page, using a local folder of release zips."""

import re

import pytest

from release_helpers import make_release_zip, write_install
from sar_log.updater import installer
from sar_log.updater.installer import InstallLayout
from sar_log.updater.sources import DirectorySource
from sar_log.updater.versions import Version, read_installed_version
from sar_log.web import create_app
from test_web_workflow import page_text


@pytest.fixture
def release_folder(tmp_path):
    folder = tmp_path / "releases"
    make_release_zip(folder, "9.0.0")
    make_release_zip(folder, "9.1.0")
    return folder


@pytest.fixture
def setup(app_config, release_folder):
    write_install(app_config.install_directory, "0.2.0")
    restarts = []
    app = create_app(app_config, update_source=DirectorySource(release_folder),
                     restart_callback=lambda: restarts.append(True))
    return app.test_client(), InstallLayout(app_config.install_directory), restarts


def test_check_shows_newest_version_and_notes(setup):
    client, layout, restarts = setup
    page = page_text(client.get("/updates?check=1"))
    assert "Version 9.1.0 is available" in page
    assert "Notes for 9.1.0" in page
    assert "update available" in page  # badge in the menu after a check


def test_install_then_restart(setup):
    client, layout, restarts = setup
    response = client.post("/updates/install", data={"version": "9.1.0"}, follow_redirects=True)
    assert "9.1.0 is downloaded and ready" in page_text(response)
    assert installer.read_pending(layout).version == "9.1.0"
    assert "is ready" in page_text(client.get("/updates"))

    response = client.post("/updates/restart")
    assert "Restarting SAR Log" in page_text(response) and restarts == [True]

    # What the launcher does next:
    installer.apply_pending(layout, install_dependencies=lambda path: None)
    assert read_installed_version(layout.install_directory) == Version(9, 1, 0)
    page = page_text(client.get("/updates"))
    assert "Updated from version 0.2.0 to 9.1.0" in page
    assert "Go back to version 0.2.0" in page


def test_cancel_and_rollback_buttons(setup):
    client, layout, restarts = setup
    client.post("/updates/install", data={"version": "9.0.0"})
    client.post("/updates/cancel")
    assert installer.read_pending(layout) is None

    response = client.post("/updates/rollback", follow_redirects=True)
    assert "no previous version" in page_text(response)

    client.post("/updates/install", data={"version": "9.0.0"})
    installer.apply_pending(layout, install_dependencies=lambda path: None)
    client.post("/updates/rollback")
    assert installer.read_pending(layout) == installer.PendingAction("rollback", "0.2.0")


def test_unknown_version_and_unreachable_source(app_config, tmp_path):
    write_install(app_config.install_directory, "0.2.0")
    client = create_app(app_config, update_source=DirectorySource(tmp_path / "missing")).test_client()
    assert "Could not check for updates" in page_text(client.get("/updates?check=1"))
    response = client.post("/updates/install", data={"version": "9.9.9"}, follow_redirects=True)
    assert "Update not installed" in page_text(response)


def test_without_launcher_restart_asks_user_to_reopen(app_config, release_folder):
    write_install(app_config.install_directory, "0.2.0")
    client = create_app(app_config, update_source=DirectorySource(release_folder)).test_client()
    client.post("/updates/install", data={"version": "9.1.0"})
    assert "Close the SAR Log window" in page_text(client.get("/updates"))


def test_git_checkout_disables_updates(app_config, release_folder):
    write_install(app_config.install_directory, "0.2.0")
    (app_config.install_directory / ".git").mkdir()
    client = create_app(app_config, update_source=DirectorySource(release_folder)).test_client()
    assert "git pull" in page_text(client.get("/updates"))


def test_health_endpoint_and_version_in_menu(setup):
    client, layout, restarts = setup
    import sar_log
    assert client.get("/updates/health").get_json() == {"app": "sar_log", "version": sar_log.__version__}
    assert re.search(rf"v{re.escape(sar_log.__version__)}", page_text(client.get("/jobs")))


def test_background_check_sets_badge(app_config, release_folder):
    from dataclasses import replace
    write_install(app_config.install_directory, "0.2.0")
    app = create_app(replace(app_config, check_for_updates_on_start=True),
                     update_source=DirectorySource(release_folder))
    import threading
    for thread in threading.enumerate():
        if thread.name == "update-check":
            thread.join(timeout=5)
    assert "update available" in page_text(app.test_client().get("/jobs"))
