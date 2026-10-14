"""Import runs: upload, match columns, check, import and undo.

See docs/specs/11-import-and-reports.md section 2. The check reads the database once
per kind of record, never once per row, and the import writes new records in bulk,
so a file of a few thousand rows stays quick.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps import events
from apps.accounts.models import User
from apps.clients.models import Client, ClientContact, Contact, Note, Tag
from apps.clients.services import client_updated
from apps.companieshouse.api import InvalidNumber, normalise_number
from apps.events.models import ActivityEvent
from apps.services import deadlines
from apps.services.models import ClientService, Deadline, FeeChange, Service
from apps.services.services import PRE_LIVE, default_settings
from apps.tasks.models import Task

from . import reading
from .fields import FIELDS, Problem, fields_for, header_key, norm, suggest
from .models import ImportedRecord, ImportRun, Kind, SavedMatching

LEFT_OUT = "(left out)"
# Event verbs that do not count as somebody changing an imported client.
QUIET_VERBS = (
    "import.",
    "deadline.generated",
    "task.generated",
    "task.due_changed",
    "companieshouse.",
    "export.",
)


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


def require_import(actor) -> None:
    if not actor.can("data.import"):
        raise PermissionDenied


# ---------------------------------------------------------------- rows


@dataclass
class Row:
    number: int  # the row in the spreadsheet; the headings are row 1
    raw: list[str]
    values: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    action: str = ""  # create or update; empty when the row has problems
    target_id: int | None = None
    label: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class CheckResult:
    rows: list[Row]

    @property
    def to_create(self) -> list[Row]:
        return [r for r in self.rows if r.ok and r.action == "create"]

    @property
    def to_update(self) -> list[Row]:
        return [r for r in self.rows if r.ok and r.action == "update"]

    @property
    def failed(self) -> list[Row]:
        return [r for r in self.rows if not r.ok]

    @property
    def counts(self) -> dict:
        return {
            "create": len(self.to_create),
            "update": len(self.to_update),
            "problems": len(self.failed),
        }


# ---------------------------------------------------------------- upload and matching


def start_run(actor, kind: str, name: str, raw: bytes) -> ImportRun:
    """Read the file and make a run with suggested (or saved) column matches."""
    require_import(actor)
    if kind not in Kind.values:
        raise ValidationError("Choose what the file holds.")
    try:
        parsed = reading.read(raw)
    except reading.FileProblem as error:
        raise ValidationError(str(error)) from None
    headers = parsed["headers"]
    saved = (
        SavedMatching.objects.filter(kind=kind, header_key=header_key(headers))
        .order_by("-updated_at")
        .first()
    )
    if saved is not None:
        mapping = {h: saved.mapping.get(h, "") for h in headers}
    else:
        mapping = suggest(kind, headers)
    run = ImportRun.objects.create(
        kind=kind,
        file_name=name[:255],
        created_by=actor,
        encoding=parsed["encoding"],
        delimiter=parsed["delimiter"],
        headers=headers,
        data=json.dumps(parsed["rows"]),
        row_count=sum(1 for r in parsed["rows"] if any(c.strip() for c in r)),
        mapping=mapping,
        matching=saved,
    )
    events.record(
        actor,
        "import.uploaded",
        f"{who(actor)} uploaded {run.file_name} for a {run.get_kind_display().lower()} import "
        f"({run.row_count} rows).",
        target=run,
    )
    return run


def rows_of(run: ImportRun) -> list[list[str]]:
    return json.loads(run.data) if run.data else []


def apply_matching(run: ImportRun, matching: SavedMatching) -> None:
    run.mapping = {h: matching.mapping.get(h, "") for h in run.headers}
    run.matching = matching
    run.save(update_fields=["mapping", "matching", "updated_at"])


def set_mapping(
    actor, run: ImportRun, mapping: dict, *, overwrite: bool, save_as: str = ""
) -> ImportRun:
    """Store the column matches. Raises ValidationError with every problem found."""
    require_import(actor)
    if run.state != ImportRun.State.UPLOADED:
        raise ValidationError("This file has already been imported.")
    known = fields_for(run.kind)
    mapping = {h: (mapping.get(h) or "") for h in run.headers}
    errors = []
    chosen = [v for v in mapping.values() if v]
    for key in chosen:
        if key not in known:
            errors.append("Choose a field from the list.")
        elif chosen.count(key) > 1:
            errors.append(f"“{known[key].label}” is matched to more than one column.")
    errors = list(dict.fromkeys(errors))
    errors += _missing_fields(run.kind, set(chosen))
    if "fee" in chosen and not actor.can("fees.view"):
        errors.append("You cannot see fees, so the fee column cannot be imported.")
    if errors:
        raise ValidationError(errors)
    run.mapping = mapping
    run.overwrite = overwrite
    save_as = save_as.strip()[:80]
    if save_as:
        run.matching, _ = SavedMatching.objects.update_or_create(
            kind=run.kind,
            name=save_as,
            defaults={
                "headers": run.headers,
                "header_key": header_key(run.headers),
                "mapping": mapping,
                "created_by": actor,
            },
        )
    run.save(update_fields=["mapping", "overwrite", "matching", "updated_at"])
    return run


def _missing_fields(kind: str, chosen: set[str]) -> list[str]:
    if kind == Kind.CLIENTS and "name" not in chosen:
        return ["Match a column to “Name”: every client needs one."]
    if kind == Kind.CONTACTS:
        errors = [] if "client" in chosen else ["Match a column to “Client”."]
        if not ({"first_name", "last_name"} <= chosen or "full_name" in chosen):
            errors.append("Match columns to “First name” and “Last name”, or to “Full name”.")
        return errors
    if kind == Kind.SERVICES:
        return [
            f"Match a column to “{label}”."
            for key, label in (("client", "Client"), ("service", "Service (name or code)"))
            if key not in chosen
        ]
    return []


# ---------------------------------------------------------------- shared lookups


def _clean_row(run: ImportRun, number: int, raw: list[str]) -> Row:
    row = Row(number=number, raw=raw)
    known = fields_for(run.kind)
    for i, heading in enumerate(run.headers):
        key = run.mapping.get(heading)
        if not key or key not in known:
            continue
        value = raw[i].strip() if i < len(raw) else ""
        if not value:
            continue
        try:
            row.values[key] = known[key].clean(value)
        except Problem as problem:
            row.problems.append(f"{known[key].label}: {problem}.")
            row.extra.setdefault("bad", set()).add(key)
    return row


def _safe_number(text: str) -> str:
    try:
        return normalise_number(text)
    except InvalidNumber:
        return ""


class ClientFinder:
    """Find a client by reference, then company number, then exact name (any case)."""

    def __init__(self):
        self.by_ref, self.by_number, self.by_name = {}, {}, {}
        self.ambiguous_names: set[str] = set()
        self.info = {}
        for pk, ref, number, name, status, ctype, since in Client.objects.values_list(
            "pk", "reference", "company_number", "name", "status", "client_type", "client_since"
        ):
            self.info[pk] = {"name": name, "status": status, "type": ctype, "since": since}
            if ref:
                self.by_ref[ref.lower()] = pk
            if number:
                self.by_number[_safe_number(number) or number] = pk
            key = name.strip().lower()
            if key in self.by_name and self.by_name[key] != pk:
                self.ambiguous_names.add(key)
            self.by_name[key] = pk

    def find(self, text: str) -> tuple[int | None, str]:
        """(client pk, problem). Accepts a reference, a company number or a name."""
        key = text.strip().lower()
        if key in self.by_ref:
            return self.by_ref[key], ""
        number = _safe_number(text)
        if number and number in self.by_number:
            return self.by_number[number], ""
        if key in self.ambiguous_names:
            return None, f"Client: more than one client is called “{text}”. Use the reference."
        if key in self.by_name:
            return self.by_name[key], ""
        return None, f"Client: no client matches “{text}”."


class PeopleFinder:
    """Staff by email or name, for manager and partner."""

    def __init__(self):
        self.by_email, self.by_name = {}, {}
        self.ambiguous: set[str] = set()
        for pk, email, name in User.objects.staff().values_list("pk", "email", "name"):
            self.by_email[email.lower()] = pk
            key = name.strip().lower()
            if key in self.by_name:
                self.ambiguous.add(key)
            self.by_name[key] = pk

    def find(self, text: str) -> int | None:
        key = text.strip().lower()
        if key in self.by_email:
            return self.by_email[key]
        if key in self.ambiguous:
            return None
        return self.by_name.get(key)


# ---------------------------------------------------------------- check


def check(run: ImportRun) -> CheckResult:
    """Work out what each row would do. Saves nothing."""
    raw_rows = rows_of(run)
    rows = [
        _clean_row(run, i + 2, raw) for i, raw in enumerate(raw_rows) if any(c.strip() for c in raw)
    ]
    {
        Kind.CLIENTS: _check_clients,
        Kind.CONTACTS: _check_contacts,
        Kind.SERVICES: _check_services,
    }[run.kind](run, rows)
    for row in rows:
        if row.problems:
            row.action = ""
    return CheckResult(rows)


def _check_clients(run: ImportRun, rows: list[Row]) -> None:
    finder = ClientFinder()
    people = PeopleFinder()
    seen: dict[tuple, int] = {}
    for row in rows:
        v = row.values
        ref = v.get("reference", "")
        number = v.get("company_number", "")
        name = v.get("name", "")
        row.label = name or ref or number
        target = None
        if ref and ref.lower() in finder.by_ref:
            target = finder.by_ref[ref.lower()]
        elif number and number in finder.by_number:
            target = finder.by_number[number]
        elif name and name.lower() in finder.ambiguous_names:
            row.problems.append(f"Name: more than one client is called “{name}”. Add a reference.")
        elif name and name.lower() in finder.by_name:
            target = finder.by_name[name.lower()]
        if ref and target and finder.by_ref.get(ref.lower(), target) != target:
            row.problems.append(f"Client reference: {ref} already belongs to another client.")
        keys = [("reference", ref.lower()), ("company number", number), ("name", name.lower())]
        for what, value in keys:
            if value and (what, value) in seen:
                row.problems.append(
                    f"Same client as row {seen[(what, value)]} (the same {what}). "
                    "Remove one of the two rows."
                )
                break
        for what, value in keys:
            if value:
                seen.setdefault((what, value), row.number)
        for key, label in (("manager", "Manager"), ("partner", "Partner")):
            if key in v:
                found = people.find(v[key])
                if found is None:
                    row.problems.append(f"{label}: nobody on the team matches “{v[key]}”.")
                else:
                    row.extra[key] = found
        if target is None:
            bad = row.extra.get("bad", set())
            if not name and "name" not in bad:
                row.problems.append("Name: needed for a new client.")
            if "client_type" not in v and "client_type" not in bad:
                row.problems.append("Type: needed for a new client.")
            row.action = "create"
        else:
            row.target_id = target
            row.label = finder.info[target]["name"]
            row.action = "update"
            if "status" in v and v["status"] != finder.info[target]["status"]:
                row.warnings.append(
                    "The status of an existing client is not changed by an import. "
                    "Change it on the client's page."
                )


def _check_contacts(run: ImportRun, rows: list[Row]) -> None:
    finder = ClientFinder()
    by_email = {}
    for pk, email in Contact.objects.exclude(email="").values_list("pk", "email"):
        by_email.setdefault(email.lower(), pk)
    links = set()
    names = {}
    mains = {}
    for client_id, contact_id, first, last, is_main in ClientContact.objects.values_list(
        "client_id", "contact_id", "contact__first_name", "contact__last_name", "is_main"
    ):
        links.add((client_id, contact_id))
        names.setdefault((client_id, f"{first} {last}".strip().lower()), contact_id)
        if is_main:
            mains[client_id] = contact_id
    seen: dict[tuple, int] = {}
    file_emails: dict[str, int] = {}
    file_mains: dict[int, int] = {}
    for row in rows:
        v = row.values
        first, last = v.get("first_name", ""), v.get("last_name", "")
        if (not first or not last) and v.get("full_name"):
            parts = v["full_name"].rsplit(" ", 1)
            first = first or parts[0]
            last = last or (parts[1] if len(parts) > 1 else "")
        v["first_name"], v["last_name"] = first, last
        full = f"{first} {last}".strip()
        row.label = full or v.get("email", "")
        client_id = None
        if "client" not in v:
            row.problems.append("Client: empty. Every person must belong to a client.")
        else:
            client_id, problem = finder.find(v["client"])
            if problem:
                row.problems.append(problem)
        row.extra["client_id"] = client_id
        email = v.get("email", "")
        key = (client_id, email or full.lower())
        if client_id and key in seen:
            row.problems.append(f"Same person as row {seen[key]}. Remove one of the two rows.")
        elif client_id:
            seen[key] = row.number
        target = by_email.get(email) if email else None
        if target is None and client_id and full:
            target = names.get((client_id, full.lower()))
        if target is None and email and email in file_emails:
            row.extra["same_as_row"] = file_emails[email]
        if target is None and "same_as_row" not in row.extra and (not first or not last):
            row.problems.append("First name and last name: needed for a new person.")
        if email:
            file_emails.setdefault(email, row.number)
        row.target_id = target
        row.action = "update" if (target or "same_as_row" in row.extra) else "create"
        row.extra["linked"] = bool(target and (client_id, target) in links)
        if v.get("is_main") and client_id and not row.problems:
            current = mains.get(client_id)
            if client_id in file_mains:
                row.warnings.append(
                    f"Row {file_mains[client_id]} already makes someone the main contact, "
                    "so this person is added without it."
                )
                v["is_main"] = False
            elif current and current != target and not run.overwrite:
                row.warnings.append(
                    "The client already has a main contact, so this person is added without it. "
                    "Tick “overwrite” to change the main contact."
                )
                v["is_main"] = False
            else:
                file_mains[client_id] = row.number


def _check_services(run: ImportRun, rows: list[Row]) -> None:
    finder = ClientFinder()
    catalogue = list(Service.objects.all())
    by_code = {s.code.lower(): s for s in catalogue}
    by_name = {norm(s.name): s for s in catalogue}
    open_rows = {
        (c, s): pk
        for pk, c, s in ClientService.objects.exclude(state=ClientService.State.ENDED).values_list(
            "pk", "client_id", "service_id"
        )
    }
    type_labels = dict(Client.Type.choices)
    seen: dict[tuple, int] = {}
    for row in rows:
        v = row.values
        client_id = service = None
        if "client" not in v:
            row.problems.append("Client: empty.")
        else:
            client_id, problem = finder.find(v["client"])
            if problem:
                row.problems.append(problem)
        if "service" not in v:
            row.problems.append("Service: empty.")
        else:
            service = by_code.get(v["service"].lower()) or by_name.get(norm(v["service"]))
            if service is None:
                row.problems.append(
                    f"Service: “{v['service']}” is not one of the practice's services. "
                    "Check the name in Settings, Services."
                )
            elif not service.active:
                row.problems.append(f"Service: {service.name} is switched off in Settings.")
        row.label = " – ".join(x for x in (v.get("client", ""), v.get("service", "")) if x)
        if client_id is None or service is None:
            continue
        info = finder.info[client_id]
        row.label = f"{info['name']} – {service.name}"
        row.extra.update(client_id=client_id, service_id=service.pk)
        if not service.applies_to_type(info["type"]):
            row.problems.append(
                f"Service: {service.name} does not apply to a "
                f"{type_labels.get(info['type'], info['type']).lower()}."
            )
        if info["status"] in (Client.Status.FORMER, Client.Status.LOST):
            row.problems.append("Client: a former or lost client cannot take services.")
        key = (client_id, service.pk)
        if key in seen:
            row.problems.append(f"Same service as row {seen[key]}. Remove one of the two rows.")
        else:
            seen[key] = row.number
        row.target_id = open_rows.get(key)
        row.action = "update" if row.target_id else "create"


# ---------------------------------------------------------------- import


def run_import(actor, run: ImportRun) -> ImportRun:
    """Save the good rows in one transaction. Rows with problems go to the failures file."""
    require_import(actor)
    if run.state != ImportRun.State.UPLOADED:
        raise ValidationError("This file has already been imported.")
    result = check(run)
    now = timezone.now()
    importer = {
        Kind.CLIENTS: _import_clients,
        Kind.CONTACTS: _import_contacts,
        Kind.SERVICES: _import_services,
    }[run.kind]
    with transaction.atomic():
        run = ImportRun.objects.select_for_update().get(pk=run.pk)
        if run.state != ImportRun.State.UPLOADED:
            raise ValidationError("This file has already been imported.")
        created, updated, after = importer(actor, run, result, now)
        run.state = ImportRun.State.DONE
        run.imported_at = now
        run.counts = {"created": created, "updated": updated, "failed": len(result.failed)}
        run.failures = json.dumps(_failure_rows(run, result.failed))
        run.data = ""  # the file itself is not kept once imported
        run.save()
        events.record(
            actor,
            "import.run",
            f"{who(actor)} imported {run.file_name} ({run.get_kind_display().lower()}): "
            f"{created} created, {updated} updated, {len(result.failed)} not imported.",
            target=run,
            counts=run.counts,
        )
    for step in after:
        step()
    return run


def _failure_rows(run: ImportRun, failed: list[Row]) -> list[dict]:
    known = fields_for(run.kind)
    hidden = {
        i
        for i, h in enumerate(run.headers)
        if run.mapping.get(h) in known and known[run.mapping[h]].sensitive
    }
    return [
        {
            "row": r.number,
            "values": [LEFT_OUT if i in hidden and c.strip() else c for i, c in enumerate(r.raw)],
            "problem": " ".join(r.problems),
        }
        for r in failed
    ]


def failure_rows(run: ImportRun) -> list[dict]:
    return json.loads(run.failures) if run.failures else []


def _tag(run: ImportRun, model: str, objects, label) -> None:
    ImportedRecord.objects.bulk_create(
        [
            ImportedRecord(
                run=run, model=model, object_id=o.pk, label=label(o)[:250], stamp=o.updated_at
            )
            for o in objects
        ]
    )


def _timeline(actor, verb: str, items: list[tuple[Client, str]]) -> None:
    """One event per client, written in bulk."""
    label = str(actor) if actor is not None else "System"
    ActivityEvent.objects.bulk_create(
        [
            ActivityEvent(
                actor=actor,
                actor_label=label[:200],
                verb=verb,
                client=client,
                client_label=f"{client.name} ({client.reference})"[:220],
                summary=summary[:500],
            )
            for client, summary in items
        ]
    )


def _empty(value) -> bool:
    return value is None or value == ""


# -- clients


def _address(v: dict) -> str:
    lines = [v.get(k, "") for k in ("address_1", "address_2", "address_3", "address_4")]
    return "\n".join(x for x in [*lines, v.get("postcode", "")] if x)


def _client_values(row: Row) -> dict:
    """Model field -> value for the row's values."""
    v = row.values
    out = {}
    simple = (
        "name",
        "client_type",
        "company_number",
        "email",
        "phone",
        "vat_number",
        "vat_frequency",
        "vat_stagger",
        "paye_reference",
        "accounts_office_reference",
        "client_since",
        "source",
    )
    for key in simple:
        if key in v:
            out[key] = v[key]
    if "manager" in row.extra:
        out["manager_id"] = row.extra["manager"]
    if "partner" in row.extra:
        out["partner_id"] = row.extra["partner"]
    address = _address(v)
    if address:
        out["correspondence_address"] = address
    if "year_end" in v:
        out["accounting_ref_day"], out["accounting_ref_month"] = v["year_end"]
    if "utr" in v:
        out["company_utr"] = v["utr"]
    return out


def _next_numbers(rows: list[Row]):
    """Automatic references (C0001, ...) above any in use or in the file."""
    top = 0
    for ref in Client.objects.filter(reference__regex=r"^C[0-9]+$").values_list(
        "reference", flat=True
    ):
        top = max(top, int(ref[1:]))
    for row in rows:
        ref = row.values.get("reference", "")
        if ref[:1] in ("C", "c") and ref[1:].isdigit():
            top = max(top, int(ref[1:]))
    while True:
        top += 1
        yield f"C{top:04d}"


def _tags_for(names: list[str], cache: dict) -> list[Tag]:
    tags = []
    for name in names:
        key = name.lower()
        if key not in cache:
            cache[key] = Tag.objects.filter(name__iexact=name).first() or Tag.objects.create(
                name=name
            )
        tags.append(cache[key])
    return tags


def _import_clients(actor, run, result: CheckResult, now):
    numbers = _next_numbers(result.to_create)
    new = []
    for row in result.to_create:
        values = _client_values(row)
        values.setdefault("status", row.values.get("status", Client.Status.ACTIVE))
        values["reference"] = row.values.get("reference") or next(numbers)
        new.append(Client(**values))
    Client.objects.bulk_create(new)
    tag_cache: dict[str, Tag] = {}
    through = Client.tags.through
    tag_links, notes = [], []
    for client, row in zip(new, result.to_create, strict=True):
        for tag in _tags_for(row.values.get("tags", []), tag_cache):
            tag_links.append(through(client_id=client.pk, tag_id=tag.pk))
        if row.values.get("notes"):
            notes.append(Note(client=client, text=row.values["notes"], author=actor))
    _tag(run, ImportedRecord.Model.CLIENT, new, lambda c: f"{c.name} ({c.reference})")
    _timeline(
        actor,
        "import.client_created",
        [(c, f"{who(actor)} created {c.name} from the import {run.file_name}.") for c in new],
    )

    updated = []
    to_update = {
        c.pk: c for c in Client.objects.filter(pk__in=[r.target_id for r in result.to_update])
    }
    for row in result.to_update:
        client = to_update[row.target_id]
        changed = _update_client(client, row, run.overwrite)
        existing_tags = {t.lower() for t in client.tags.values_list("name", flat=True)}
        for tag in _tags_for(row.values.get("tags", []), tag_cache):
            if tag.name.lower() not in existing_tags:
                tag_links.append(through(client_id=client.pk, tag_id=tag.pk))
                changed.append("tags")
        text = row.values.get("notes")
        if text and not client.notes.filter(text=text).exists():
            notes.append(Note(client=client, text=text, author=actor))
            changed.append("notes")
        if changed:
            updated.append((client, changed))
    through.objects.bulk_create(tag_links, ignore_conflicts=True)
    Note.objects.bulk_create(notes)
    _timeline(
        actor,
        "import.client_updated",
        [
            (c, f"{who(actor)} filled in {', '.join(sorted(set(f)))} from {run.file_name}.")
            for c, f in updated
        ],
    )

    def after():
        for client, _fields in updated:
            client_updated.send(sender=Client, client=client, actor=actor)

    return len(new), len(updated), [after]


LABELS = {
    "accounting_ref_day": "year end",
    "accounting_ref_month": "year end",
    "company_utr": "UTR",
    "manager_id": "manager",
    "partner_id": "partner",
    "correspondence_address": "address",
}


def _update_client(client: Client, row: Row, overwrite: bool) -> list[str]:
    """Fill the client's empty fields (or all, with overwrite). Returns the labels changed."""
    values = _client_values(row)
    if not overwrite:
        values.pop("name", None)
    if client.company_number:
        values.pop("company_number", None)
    if client.last_synced_at:
        # Companies House owns the year end once a company is synced.
        values.pop("accounting_ref_day", None)
        values.pop("accounting_ref_month", None)
    changed_fields, labels = [], []
    for key, value in values.items():
        current = getattr(client, key)
        if current == value or (not overwrite and not _empty(current)):
            continue
        setattr(client, key, value)
        changed_fields.append(key)
        labels.append(LABELS.get(key, key.replace("_", " ")))
    if changed_fields:
        client.save(update_fields=[*changed_fields, "updated_at"])
    return labels


# -- contacts


CONTACT_FIELDS = ("title", "email", "mobile", "phone", "date_of_birth")


def _import_contacts(actor, run, result: CheckResult, now):
    clients = {c.pk: c for c in Client.objects.filter(pk__in=_client_ids(result))}
    created_contacts: dict[int, Contact] = {}  # row number -> new contact
    new_contacts = []
    for row in result.to_create:
        v = row.values
        contact = Contact(
            first_name=v["first_name"],
            last_name=v["last_name"],
            **{k: v[k] for k in CONTACT_FIELDS if k in v},
        )
        created_contacts[row.number] = contact
        new_contacts.append(contact)
    Contact.objects.bulk_create(new_contacts)

    existing = {
        c.pk: c
        for c in Contact.objects.filter(
            pk__in=[r.target_id for r in result.to_update if r.target_id]
        )
    }
    links = {
        (link.client_id, link.contact_id): link
        for link in ClientContact.objects.filter(client_id__in=clients)
    }
    updated = 0
    new_links, timeline = [], []
    for row in [*result.to_create, *result.to_update]:
        v = row.values
        client = clients[row.extra["client_id"]]
        if row.number in created_contacts:
            contact, did = created_contacts[row.number], False
        elif row.target_id:
            contact = existing[row.target_id]
            did = _update_contact(contact, row, run.overwrite)
        else:
            contact, did = created_contacts[row.extra["same_as_row"]], False
        if v.get("is_main"):
            ClientContact.objects.filter(client=client, is_main=True).exclude(
                contact=contact
            ).update(is_main=False, updated_at=now)
        link = links.get((client.pk, contact.pk))
        if link is None:
            link = ClientContact(
                client=client,
                contact=contact,
                roles=v.get("role", []),
                is_main=bool(v.get("is_main")),
                receives_reminders=v.get("receives_reminders", True),
            )
            new_links.append(link)
            links[(client.pk, contact.pk)] = link
            timeline.append(
                (client, f"{who(actor)} added {contact.full_name} from {run.file_name}.")
            )
            did = True
        elif _update_link(link, v, run.overwrite):
            did = True
        if did and row.number not in created_contacts:
            updated += 1
    ClientContact.objects.bulk_create(new_links)
    _tag(run, ImportedRecord.Model.CONTACT, new_contacts, lambda c: c.full_name)
    _tag(
        run,
        ImportedRecord.Model.LINK,
        new_links,
        lambda link: f"{link.contact.full_name} at {link.client.name}",
    )
    _timeline(actor, "import.contact_added", timeline)
    return len(new_contacts), updated, []


def _client_ids(result: CheckResult) -> set[int]:
    return {r.extra["client_id"] for r in [*result.to_create, *result.to_update]}


def _update_contact(contact: Contact, row: Row, overwrite: bool) -> bool:
    v = row.values
    fields = list(CONTACT_FIELDS) + (["first_name", "last_name"] if overwrite else [])
    changed = []
    for key in fields:
        if key not in v or not v[key]:
            continue
        current = getattr(contact, key)
        if current == v[key] or (not overwrite and not _empty(current)):
            continue
        setattr(contact, key, v[key])
        changed.append(key)
    if changed:
        contact.save(update_fields=[*changed, "updated_at"])
    return bool(changed)


def _update_link(link: ClientContact, v: dict, overwrite: bool) -> bool:
    changed = []
    roles = v.get("role", [])
    if roles:
        merged = roles if overwrite else list(dict.fromkeys([*link.roles, *roles]))
        if merged != link.roles:
            link.roles = merged
            changed.append("roles")
    if v.get("is_main") and not link.is_main:
        link.is_main = True
        changed.append("is_main")
    if (
        "receives_reminders" in v
        and overwrite
        and v["receives_reminders"] != link.receives_reminders
    ):
        link.receives_reminders = v["receives_reminders"]
        changed.append("receives_reminders")
    if changed:
        link.save(update_fields=[*changed, "updated_at"])
    return bool(changed)


# -- services


def _import_services(actor, run, result: CheckResult, now):
    today = timezone.localdate()
    clients = {c.pk: c for c in Client.objects.filter(pk__in=_client_ids(result))}
    services = {s.pk: s for s in Service.objects.all()}
    new = []
    for row in result.to_create:
        v = row.values
        client = clients[row.extra["client_id"]]
        service = services[row.extra["service_id"]]
        proposed = client.status in PRE_LIVE
        new.append(
            ClientService(
                client=client,
                service=service,
                state=ClientService.State.PROPOSED if proposed else ClientService.State.ACTIVE,
                fee_amount=v.get("fee"),
                fee_frequency=v.get("frequency", ClientService.Frequency.MONTHLY),
                starts_on=None
                if proposed
                else (v.get("start_date") or client.client_since or today),
                settings=default_settings(service),
            )
        )
    ClientService.objects.bulk_create(new)
    changes = [
        FeeChange(
            client_service=cs,
            new_amount=cs.fee_amount,
            new_frequency=cs.fee_frequency,
            effective_on=cs.starts_on or today,
            changed_by=actor,
            reason=f"Imported from {run.file_name}"[:300],
        )
        for cs in new
    ]
    updated = 0
    rows = {
        cs.pk: cs
        for cs in ClientService.objects.filter(pk__in=[r.target_id for r in result.to_update])
    }
    for row in result.to_update:
        cs = rows[row.target_id]
        v = row.values
        old_amount, old_frequency = cs.fee_amount, cs.fee_frequency
        fields = []
        if "fee" in v and (run.overwrite or cs.fee_amount is None) and v["fee"] != cs.fee_amount:
            cs.fee_amount = v["fee"]
            fields.append("fee_amount")
            if "frequency" in v:
                cs.fee_frequency = v["frequency"]
                fields.append("fee_frequency")
        new_start = v.get("start_date")
        if (
            new_start
            and cs.state == ClientService.State.ACTIVE
            and (run.overwrite or cs.starts_on is None)
            and cs.starts_on != new_start
        ):
            cs.starts_on = new_start
            fields.append("starts_on")
        if fields:
            cs.save(update_fields=[*fields, "updated_at"])
            updated += 1
            if "fee_amount" in fields:
                changes.append(
                    FeeChange(
                        client_service=cs,
                        old_amount=old_amount,
                        new_amount=cs.fee_amount,
                        old_frequency=old_frequency,
                        new_frequency=cs.fee_frequency,
                        changed_by=actor,
                        reason=f"Imported from {run.file_name}"[:300],
                    )
                )
    FeeChange.objects.bulk_create(changes)
    _tag(
        run,
        ImportedRecord.Model.SERVICE,
        new,
        lambda cs: f"{cs.service.name} for {cs.client.name}",
    )
    per_client: dict[int, list[str]] = {}
    for cs in new:
        per_client.setdefault(cs.client_id, []).append(cs.service.name)
    _timeline(
        actor,
        "import.services_added",
        [
            (clients[pk], f"{who(actor)} added {', '.join(names)} from {run.file_name}.")
            for pk, names in per_client.items()
        ],
    )
    touched = {cs.client_id for cs in new} | {rows[r.target_id].client_id for r in result.to_update}

    def after():
        for pk in sorted(touched):
            deadlines.generate_for_client(clients[pk], actor=actor)
        _restamp(run, ImportedRecord.Model.SERVICE, ClientService)

    return len(new), updated, [after]


def _restamp(run: ImportRun, model: str, klass) -> None:
    """Move the stamps on after the system has touched what the run created."""
    stamps = dict(
        klass.objects.filter(
            pk__in=run.records.filter(model=model).values("object_id")
        ).values_list("pk", "updated_at")
    )
    for record in run.records.filter(model=model):
        if record.object_id in stamps and stamps[record.object_id] != record.stamp:
            record.stamp = stamps[record.object_id]
            record.save(update_fields=["stamp", "updated_at"])


# ---------------------------------------------------------------- undo


def _changed_clients(run: ImportRun, ids: list[int]) -> dict[int, str]:
    """Clients somebody has worked on since the import, with the reason."""
    since = run.imported_at or run.created_at
    reasons = {}
    for pk, verb in ActivityEvent.objects.filter(
        client_id__in=ids, created_at__gt=since
    ).values_list("client_id", "verb"):
        if not verb.startswith(QUIET_VERBS):
            reasons.setdefault(pk, "Somebody has worked on this client since the import.")
    for pk in (
        Task.objects.filter(client_id__in=ids)
        .exclude(source=Task.Source.GENERATED)
        .values_list("client_id", flat=True)
    ):
        reasons.setdefault(pk, "It has tasks added by hand.")
    for pk in Task.objects.filter(client_id__in=ids, completed_at__isnull=False).values_list(
        "client_id", flat=True
    ):
        reasons.setdefault(pk, "Work has been completed for it.")
    return reasons


def undo(actor, run: ImportRun) -> ImportRun:
    """Delete what the run created and nobody has changed since. Lists what stayed."""
    require_import(actor)
    if run.state != ImportRun.State.DONE:
        raise ValidationError("Only an import that has run can be undone.")
    kept: list[dict] = []
    removed = 0
    records = list(run.records.all())
    by_model: dict[str, list[ImportedRecord]] = {}
    for r in records:
        by_model.setdefault(r.model, []).append(r)
    late = timedelta(seconds=1)

    def stale(record, obj) -> bool:
        return obj.updated_at > record.stamp + late

    with transaction.atomic():
        # Services first, then links, people and clients, so nothing is left hanging.
        recs = by_model.get(ImportedRecord.Model.SERVICE, [])
        found = {
            cs.pk: cs for cs in ClientService.objects.filter(pk__in=[r.object_id for r in recs])
        }
        for record in recs:
            cs = found.get(record.object_id)
            if cs is None:
                record.delete()
                continue
            reason = ""
            if stale(record, cs):
                reason = "It has been changed since the import."
            elif cs.fee_changes.count() > 1:
                reason = "Its fee has been changed since the import."
            elif cs.deadlines.exclude(status=Deadline.Status.OPEN).exists():
                reason = "Some of its deadlines have been marked."
            if reason:
                kept.append({"label": record.label, "reason": reason})
                continue
            open_deadlines = cs.deadlines.filter(status=Deadline.Status.OPEN)
            Task.objects.filter(
                deadline__in=open_deadlines, source=Task.Source.GENERATED, completed_at__isnull=True
            ).delete()
            open_deadlines.delete()
            cs.delete()
            record.delete()
            removed += 1

        recs = by_model.get(ImportedRecord.Model.LINK, [])
        found = {
            link.pk: link
            for link in ClientContact.objects.filter(pk__in=[r.object_id for r in recs])
        }
        for record in recs:
            link = found.get(record.object_id)
            if link is None:
                record.delete()
            elif stale(record, link):
                kept.append({"label": record.label, "reason": "It has been changed since."})
            else:
                link.delete()
                record.delete()
                removed += 1

        recs = by_model.get(ImportedRecord.Model.CONTACT, [])
        found = {c.pk: c for c in Contact.objects.filter(pk__in=[r.object_id for r in recs])}
        for record in recs:
            contact = found.get(record.object_id)
            if contact is None:
                record.delete()
            elif stale(record, contact) or contact.portal_user_id:
                kept.append({"label": record.label, "reason": "Their details have changed since."})
            elif contact.client_links.exists():
                kept.append(
                    {"label": record.label, "reason": "They have been linked to a client since."}
                )
            else:
                contact.delete()
                record.delete()
                removed += 1

        recs = by_model.get(ImportedRecord.Model.CLIENT, [])
        found = {c.pk: c for c in Client.objects.filter(pk__in=[r.object_id for r in recs])}
        changed = _changed_clients(run, list(found))
        for record in recs:
            client = found.get(record.object_id)
            if client is None:
                record.delete()
                continue
            reason = (
                "It has been changed since the import." if stale(record, client) else ""
            ) or changed.get(client.pk, "")
            if reason:
                kept.append({"label": record.label, "reason": reason})
                continue
            client.delete()
            record.delete()
            removed += 1

        run.state = ImportRun.State.UNDONE
        run.undone_at = timezone.now()
        run.undone_by = actor
        run.undo_report = kept
        run.counts = {**run.counts, "removed": removed, "kept": len(kept)}
        run.save()
        events.record(
            actor,
            "import.undone",
            f"{who(actor)} undid the import of {run.file_name}: {removed} removed, "
            f"{len(kept)} kept because they had changed.",
            target=run,
            removed=removed,
            kept=len(kept),
        )
    return run


# ---------------------------------------------------------------- Companies House


def companies_to_fetch(run: ImportRun):
    ids = run.records.filter(model=ImportedRecord.Model.CLIENT).values("object_id")
    return Client.objects.filter(pk__in=ids).exclude(company_number="").order_by("pk")


def request_fetch(actor, run: ImportRun) -> ImportRun:
    """Ask the worker to fetch every company this run created."""
    from apps.jobs import services as jobs

    require_import(actor)
    if run.kind != Kind.CLIENTS or run.state != ImportRun.State.DONE:
        raise ValidationError("Only a clients import that has run can fetch from Companies House.")
    if run.fetch_active:
        return run
    total = companies_to_fetch(run).count()
    if not total:
        raise ValidationError("None of the imported clients has a company number.")
    run.fetch_state = ImportRun.FetchState.WAITING
    run.fetch_total = total
    run.fetch_done = run.fetch_failed = 0
    run.save(
        update_fields=["fetch_state", "fetch_total", "fetch_done", "fetch_failed", "updated_at"]
    )
    jobs.request_run(actor, "import_fetch")
    events.record(
        actor,
        "import.fetch_requested",
        f"{who(actor)} asked to fetch {total} imported companies from Companies House.",
        target=run,
    )
    return run


__all__ = ["FIELDS", "check", "run_import", "undo", "request_fetch", "start_run"]
