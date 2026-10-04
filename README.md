# SAR Log

Local job, person-hours and training records for a SAR group. Runs on one
machine, in the browser, at http://127.0.0.1:8765 — it is not reachable from
other computers or the internet.

## Windows: first install
1. Install Python: `winget install Python.Python.3.12` in PowerShell, or the
   python.org installer with "Add python.exe to PATH" ticked.
2. Download the latest release zip: on GitHub, *Tags* → newest `vX.Y.Z` →
   *Download ZIP*. **Do not `git clone`** for a user install — in-app updates
   are switched off in git checkouts.
3. Unzip to `C:\SAR_Log` (not Documents/Desktop, which may sync to OneDrive).
4. Double-click `run_sar_log.bat`. The first run installs what it needs; after
   that it starts the app and opens the browser. Close the window to stop it.

## Updates
The menu shows the version and an "update available" badge when GitHub has a
newer release. The Updates page downloads it; "Restart now" applies it. Code
is swapped, never `data/`; the replaced version is kept in `updates/previous`
so "Go back" can undo it. See `RELEASING.md` for publishing a release.

Data lives in `data/sar_log.sqlite`. A backup copy is written to
`data/backups/` every time the app starts (latest 30 kept). **Copy the `data`
folder to keep an off-machine backup.** Never email or upload it — it holds
personal and health details.

## Commands
    python -m sar_log launch         # what the .bat runs: apply updates, serve, restart on request
    python -m sar_log serve          # back up, then start the app
    python -m sar_log backup         # backup now
    python -m sar_log --database try.sqlite demo   # made-up data to explore
    python -m pytest                 # run the tests

## Ideas behind it
- **Jobs**: event number, date, name and notes are fixed; every other detail is
  a *field* managed on the Fields page. Add a field once and it appears in the
  job form, filters, reports and exports. Archive fields instead of deleting.
- **Hours**: one row per person per job. Totals, staff counts and hours per
  organisation are always calculated, never typed.
- **Training**: a session (date + training type) and who attended. Types can
  have a validity period so qualifications expire.
- **History**: every change is logged on the History page.
