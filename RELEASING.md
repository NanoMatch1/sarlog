# Releasing a new version

Users only ever receive **tagged** versions, so pushing work to `develop` is
always safe. A release is a tag `vX.Y.Z` on a commit where:

1. `sar_log/__init__.py` has `__version__ = "X.Y.Z"` (the only place the
   version is written).
2. `CHANGELOG.md` has a `## vX.Y.Z — date` section, written for the user —
   it is what the Updates page shows. A test fails if this is missing.
3. If the database structure changed: `schema.sql` describes the new schema
   **and** a `Migration` in `sar_log/database.py` upgrades older databases.
4. `python -m pytest` passes.

Then:

    git commit -am "Release vX.Y.Z"
    git tag vX.Y.Z
    git push origin develop vX.Y.Z

Within seconds the app's Updates page offers it. Optionally, also create a
GitHub Release from the tag for a nicer page; the app only needs the tag.

## Trying an update without GitHub (simulation mode)
Put release zips named `vX.Y.Z.zip` (laid out like GitHub's: one top folder
containing the repository) in a folder, then on an unzipped copy:

    python -m sar_log --update-source-dir C:\path\to\zips launch
