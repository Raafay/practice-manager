"""Demo data for imports: a saved matching, a past clients import with a failed row, and a
contacts import giving each imported client its main contact.

Everything here is made up. Safe to run twice.
"""

from apps.accounts.models import User
from apps.imports import services
from apps.imports.fields import header_key
from apps.imports.models import ImportRun, SavedMatching

FILE_NAME = "demo-old-system-clients.csv"
HEADERS = ["Client Code", "Client Name", "Client Type", "Year End", "Email", "Client Since", "Tags"]
ROWS = [
    "D901,Orchard Lane Example Ltd,Limited Company,31/03,orchard@example.com,01/04/2018,Imported",
    "D902,Pebble Example Design,Sole trader,05/04,pebble@example.com,2019-06-01,Imported",
    "D903,Quarry Example Partners,Partnership,30/04,,15/05/2020,Imported",
    "D904,Rook Example Ltd,Company of some kind,31/12,,01/01/2021,Imported",
]
CONTACTS_FILE = "demo-old-system-contacts.csv"
CONTACTS = [
    "Client Code,First Name,Surname,Email,Role,Main Contact",
    "D901,Olive,Orchardson,olive.orchardson@example.com,Director,Yes",
    "D902,Piper,Pebbleton,piper.pebbleton@example.com,Other,Yes",
    "D903,Quinn,Quarrier,quinn.quarrier@example.com,Partner,Yes",
]


def seed() -> dict:
    if ImportRun.objects.filter(file_name=FILE_NAME).exists():
        return {"import_runs": 0}
    actor = User.objects.active_owners().order_by("pk").first()
    if actor is None:
        return {"import_runs": 0}
    raw = ("\n".join([",".join(HEADERS), *ROWS]) + "\n").encode()
    run = services.start_run(actor, "clients", FILE_NAME, raw)
    services.set_mapping(actor, run, run.mapping, overwrite=False)
    SavedMatching.objects.get_or_create(
        kind="clients",
        name="Old system clients",
        defaults={
            "headers": HEADERS,
            "header_key": header_key(HEADERS),
            "mapping": run.mapping,
            "created_by": actor,
        },
    )
    services.run_import(actor, run)
    people = services.start_run(
        actor, "contacts", CONTACTS_FILE, ("\n".join(CONTACTS) + "\n").encode()
    )
    services.set_mapping(actor, people, people.mapping, overwrite=False)
    services.run_import(actor, people)
    return {"import_runs": 2}
