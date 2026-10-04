"""Build fake installs and GitHub-style release zips for updater tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

CHANGELOG_TEMPLATE = "# Changelog\n\n## v{version} — 2026-10-05\n- Notes for {version}.\n\n## v0.1.0\n- First.\n"


def release_files(version: str, extra_files: dict[str, str] | None = None,
                  pyproject: str = "[project]\nname = 'sar-log'\n") -> dict[str, str]:
    files = {
        "sar_log/__init__.py": f'"""SAR Log."""\n\n__version__ = "{version}"\n',
        "sar_log/module.py": f"VERSION_MARKER = '{version}'\n",
        "run_sar_log.bat": f"rem launcher {version}\n",
        "pyproject.toml": pyproject,
        "CHANGELOG.md": CHANGELOG_TEMPLATE.format(version=version),
    }
    files.update(extra_files or {})
    return files


def write_install(install_directory: Path, version: str, **kwargs) -> Path:
    """A user's install folder: release files plus data/ and .venv/ that updates must not touch."""
    for relative_path, content in release_files(version, **kwargs).items():
        target = install_directory / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (install_directory / "data").mkdir(parents=True, exist_ok=True)
    (install_directory / "data" / "sar_log.sqlite").write_text("precious records")
    (install_directory / ".venv").mkdir(exist_ok=True)
    (install_directory / ".venv" / "marker").write_text("environment")
    return install_directory


def make_release_zip(directory: Path, version: str, files: dict[str, str] | None = None,
                     top_folder: str | None = None) -> Path:
    """A zip laid out like GitHub's tag download: one top-level folder."""
    directory.mkdir(parents=True, exist_ok=True)
    zip_path = directory / f"v{version}.zip"
    top_folder = top_folder or f"sarlog-{version}"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(f"{top_folder}/", "")
        for relative_path, content in (files if files is not None else release_files(version)).items():
            archive.writestr(f"{top_folder}/{relative_path}", content)
    return zip_path
