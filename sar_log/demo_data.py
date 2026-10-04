"""Synthetic data for trying the app and for tests. Contains no real people.

Deterministic for a given seed, so a demo database is reproducible.
"""

from __future__ import annotations

import datetime
import random
import sqlite3

from sar_log import fields, jobs, organisations, people, training
from sar_log.jobs import JobInput
from sar_log.people import PersonInput

FIRST_NAMES = ["Aroha", "Ben", "Chloe", "Dan", "Ella", "Finn", "Grace", "Hemi", "Isla", "Jack",
               "Kiri", "Liam", "Mia", "Nikau", "Olivia", "Pita", "Quinn", "Ruby", "Sam", "Tama"]
LAST_NAMES = ["Example", "Sample", "Testperson", "Placeholder", "Demo"]
ORGANISATION_NAMES = ["Demo LandSAR Group", "Neighbour LandSAR Group", "Police", "Coastguard"]
TRAINING_TYPES = [("River safety", 24), ("Stretcher bearing", None), ("First aid", 24),
                  ("Navigation", None), ("Search techniques", None)]
LOCATIONS = ["Demo Range", "Example Forest Park", "Sample Beach", "Test River"]


def populate_demo_data(connection: sqlite3.Connection, seed: int = 1,
                       today: datetime.date = datetime.date(2026, 10, 1),
                       person_count: int = 20, job_count: int = 40, session_count: int = 25) -> None:
    random_source = random.Random(seed)

    organisation_list = [organisations.create_organisation(connection, name)
                         for name in ORGANISATION_NAMES]
    home_organisation = organisation_list[0]

    person_list = []
    for index in range(person_count):
        joined = today - datetime.timedelta(days=random_source.randint(60, 3000))
        has_left = random_source.random() < 0.15
        person_list.append(people.create_person(connection, PersonInput(
            full_name=f"{FIRST_NAMES[index % len(FIRST_NAMES)]} {random_source.choice(LAST_NAMES)}",
            sar_id=f"DEMO{index + 1:03d}",
            organisation_id=(home_organisation.id if random_source.random() < 0.75
                             else random_source.choice(organisation_list[1:]).id),
            joined_date=joined.isoformat(),
            left_date=(today - datetime.timedelta(days=random_source.randint(1, 50))).isoformat()
            if has_left else "",
        )))

    type_list = [training.create_training_type(connection, name, validity_months=validity)
                 for name, validity in TRAINING_TYPES]
    for _ in range(session_count):
        attendees = random_source.sample(person_list, random_source.randint(3, 10))
        training.create_training_session(
            connection,
            (today - datetime.timedelta(days=random_source.randint(1, 900))).isoformat(),
            random_source.choice(type_list).id,
            [person.id for person in attendees],
        )

    definitions = {definition.key: definition for definition in fields.list_field_definitions(connection)}
    lost_party_choices = definitions["lost_party_type"].choices
    district_choices = definitions["district"].choices
    for index in range(job_count):
        start_date = today - datetime.timedelta(days=random_source.randint(1, 1100))
        environment = "Marine" if random_source.random() < 0.2 else "Land"
        raw_values = {
            "environment": [environment],
            "district": [random_source.choice(district_choices)],
            "location": [random_source.choice(LOCATIONS)],
            "days": [str(random_source.choice([1, 1, 1, 2, 3]))],
            "lost_party_type": random_source.sample(lost_party_choices, random_source.choice([1, 1, 2])),
            "plb": [random_source.choice(["yes", "no", ""])],
            "injured": [random_source.choice(["yes", "no", "no"])],
            "logged_in_d4h": ["yes"],
        }
        job = jobs.create_job(connection, JobInput(
            event_number=f"DEMO-{start_date.year}-{index + 1:03d}",
            start_date=start_date.isoformat(),
            name=f"Demo job {index + 1}",
            raw_field_values=raw_values,
        ))
        for person in random_source.sample(person_list, random_source.randint(2, 8)):
            jobs.set_attendance(connection, job.id, person.id,
                                random_source.choice([2, 3.5, 4, 6, 8, 11]))
