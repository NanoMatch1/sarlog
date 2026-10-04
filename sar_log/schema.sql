-- SAR log schema, version 1.
--
-- Design notes
-- * Jobs keep only their identity columns (event number, date, name, notes).
--   Every other job detail is a *field definition* (field_definition) with
--   values stored in job_field_value. Adding a new reportable detail is one
--   row in field_definition, made from the UI; forms, filters, reports and
--   exports all read the definitions, so nothing else needs editing.
-- * Totals (person hours, staff count, hours per organisation) are never
--   stored. They are computed from job_attendance so they cannot drift.
-- * Dates are ISO-8601 text (YYYY-MM-DD), which sorts and compares correctly.

CREATE TABLE IF NOT EXISTS schema_info (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organisation (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    notes   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS person (
    id              INTEGER PRIMARY KEY,
    sar_id          TEXT UNIQUE,
    full_name       TEXT NOT NULL,
    organisation_id INTEGER REFERENCES organisation(id) ON DELETE SET NULL,
    joined_date     TEXT,
    left_date       TEXT,
    email           TEXT NOT NULL DEFAULT '',
    phone           TEXT NOT NULL DEFAULT '',
    comments        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS job (
    id           INTEGER PRIMARY KEY,
    event_number TEXT NOT NULL UNIQUE,
    start_date   TEXT NOT NULL,
    name         TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS job_start_date_index ON job(start_date);

CREATE TABLE IF NOT EXISTS field_definition (
    key          TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    value_type   TEXT NOT NULL,
    section      TEXT NOT NULL DEFAULT 'Details',
    description  TEXT NOT NULL DEFAULT '',
    choices_json TEXT NOT NULL DEFAULT '[]',
    is_required  INTEGER NOT NULL DEFAULT 0,
    is_archived  INTEGER NOT NULL DEFAULT 0,
    sort_order   INTEGER NOT NULL DEFAULT 0
);

-- One row per stored value. Multi-choice fields store one row per selected
-- choice, which is what makes "count jobs per choice" a plain GROUP BY.
CREATE TABLE IF NOT EXISTS job_field_value (
    job_id    INTEGER NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    field_key TEXT NOT NULL REFERENCES field_definition(key) ON UPDATE CASCADE,
    value     TEXT NOT NULL,
    PRIMARY KEY (job_id, field_key, value)
);

CREATE INDEX IF NOT EXISTS job_field_value_field_index ON job_field_value(field_key, value);

-- The organisation is recorded per attendance (defaulting to the person's
-- organisation at the time) so that historic hours-by-organisation reports do
-- not change when a person later moves group.
CREATE TABLE IF NOT EXISTS job_attendance (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    person_id       INTEGER NOT NULL REFERENCES person(id) ON DELETE RESTRICT,
    organisation_id INTEGER REFERENCES organisation(id) ON DELETE SET NULL,
    hours           REAL NOT NULL CHECK (hours >= 0),
    role            TEXT NOT NULL DEFAULT '',
    UNIQUE (job_id, person_id)
);

CREATE TABLE IF NOT EXISTS training_type (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description     TEXT NOT NULL DEFAULT '',
    validity_months INTEGER CHECK (validity_months IS NULL OR validity_months > 0),
    is_archived     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS training_session (
    id               INTEGER PRIMARY KEY,
    session_date     TEXT NOT NULL,
    training_type_id INTEGER NOT NULL REFERENCES training_type(id) ON DELETE RESTRICT,
    title            TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS training_session_date_index ON training_session(session_date);

CREATE TABLE IF NOT EXISTS training_attendance (
    session_id INTEGER NOT NULL REFERENCES training_session(id) ON DELETE CASCADE,
    person_id  INTEGER NOT NULL REFERENCES person(id) ON DELETE RESTRICT,
    PRIMARY KEY (session_id, person_id)
);

-- Append-only record of every change made through the application.
CREATE TABLE IF NOT EXISTS change_log (
    id          INTEGER PRIMARY KEY,
    changed_at  TEXT NOT NULL,
    entity      TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    action      TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
