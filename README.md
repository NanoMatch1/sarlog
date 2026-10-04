# SAR Log

Local job, person-hours and training records for a SAR group. Runs on one
machine, in the browser, at http://127.0.0.1:8765 — it is not reachable from
other computers or the internet.

## Windows: first use
1. Install Python 3.11+ from python.org (tick "Add python.exe to PATH").
2. Double-click `run_sar_log.bat`. The first run installs what it needs; after
   that it starts the app and opens the browser. Close the window to stop it.

Data lives in `data/sar_log.sqlite`. A backup copy is written to
`data/backups/` every time the app starts (latest 30 kept). **Copy the `data`
folder to keep an off-machine backup.** Never email or upload it — it holds
personal and health details.

## Commands
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
