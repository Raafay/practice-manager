"""Made-up clients, people, notes and documents for development. Everything here is invented.

Safe to run twice: a client is looked up by name and left alone if it exists.
"""

from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import Team, User

from . import services
from .models import (
    Client,
    ClientContact,
    ClientLink,
    Contact,
    CustomFieldDefinition,
    Document,
    Tag,
)

T = Client.Type
S = Client.Status

# name, type, status
CLIENTS = [
    ("Marlow & Finch Design Ltd", T.LTD, S.ACTIVE),
    ("Brightwater Plumbing Ltd", T.LTD, S.ACTIVE),
    ("Ashgrove Bakery Ltd", T.LTD, S.ACTIVE),
    ("Copperleaf Consulting Ltd", T.LTD, S.ACTIVE),
    ("Dunmore Logistics Ltd", T.LTD, S.ACTIVE),
    ("Elmstead Dental Ltd", T.LTD, S.ACTIVE),
    ("Fernhill Interiors Ltd", T.LTD, S.PAUSED),
    ("Gannet Marine Services Ltd", T.LTD, S.ACTIVE),
    ("Hollin Park Estates Ltd", T.LTD, S.ONBOARDING),
    ("Ivybridge Software Ltd", T.LTD, S.ACTIVE),
    ("Juniper Lane Events Ltd", T.LTD, S.FORMER),
    ("Kestrel Holdings plc", T.PLC, S.ACTIVE),
    ("Larkfield Architects LLP", T.LLP, S.ACTIVE),
    ("Millbrook Surveyors LLP", T.LLP, S.ONBOARDING),
    ("Nettlebed & Sons", T.PARTNERSHIP, S.ACTIVE),
    ("Oakley Farm Partnership", T.PARTNERSHIP, S.ACTIVE),
    ("Ruth Penhallow (joiner)", T.SOLE_TRADER, S.ACTIVE),
    ("Quentin Rudd (photographer)", T.SOLE_TRADER, S.ACTIVE),
    ("Saskia Thorne (tutor)", T.SOLE_TRADER, S.PAUSED),
    ("Tobias Underhill (mechanic)", T.SOLE_TRADER, S.ACTIVE),
    ("Ursula Vane (illustrator)", T.SOLE_TRADER, S.FORMER),
    ("Wilfred Ashby", T.INDIVIDUAL, S.ACTIVE),
    ("Xanthe Brook", T.INDIVIDUAL, S.ACTIVE),
    ("Yusuf Calloway", T.INDIVIDUAL, S.ACTIVE),
    ("Zara Delaney", T.INDIVIDUAL, S.ONBOARDING),
    ("The Harrowby Family Trust", T.TRUST, S.ACTIVE),
    ("Riverside Community Garden", T.CHARITY, S.ACTIVE),
    ("Old Mill Heritage Society", T.CHARITY, S.ACTIVE),
    ("Brindle Social Club", T.OTHER, S.ACTIVE),
    ("Pennine Walkers Association", T.OTHER, S.LOST),
]
# Three prospects as well, so the status filter has something to show.
CLIENTS += [
    ("Windermere Wholefoods Ltd", T.LTD, S.PROSPECT),
    ("Foxglove Florists Ltd", T.LTD, S.PROSPECT),
    ("Greaves & Daughter", T.PARTNERSHIP, S.LOST),
]

FIRST = [
    "Alder",
    "Bryony",
    "Cedric",
    "Delphine",
    "Emrys",
    "Fenella",
    "Gideon",
    "Honor",
    "Ignatius",
    "Jessamy",
    "Kit",
    "Linnet",
    "Marcus",
    "Nerys",
    "Orla",
    "Peregrine",
    "Quill",
    "Rosalind",
    "Silas",
    "Tamsin",
    "Ulric",
    "Verity",
    "Wystan",
    "Xena",
    "Yorick",
    "Zillah",
    "Amias",
    "Beatrix",
    "Caspian",
    "Dilys",
    "Eira",
    "Fitz",
    "Gwen",
    "Hamish",
    "Isolde",
    "Jago",
    "Kerensa",
    "Lorcan",
    "Morwenna",
    "Nye",
    "Oriel",
    "Piran",
    "Rhosyn",
    "Seren",
    "Tegan",
    "Uther",
    "Vaughan",
    "Wenna",
    "Ynys",
    "Zennor",
]
LAST = [
    "Ashworth",
    "Bellamy",
    "Carew",
    "Dunstan",
    "Everard",
    "Fairweather",
    "Garland",
    "Haddon",
    "Ingleby",
    "Jessop",
    "Kemble",
    "Lovell",
    "Marlowe",
    "Netherby",
    "Orchard",
    "Penrose",
    "Quennell",
    "Radcliffe",
    "Stannard",
    "Thackeray",
    "Underwood",
    "Vickery",
    "Wetherby",
    "Yardley",
    "Zouch",
]

SAMPLE_NOTES = [
    ("Prefers email to phone calls. Year-end papers usually arrive late.", True),
    ("Asked about adding payroll from next April.", False),
    ("Director away in August. Send reminders in July.", False),
]


def sample_pdf() -> bytes:
    import logging

    from weasyprint import HTML

    for noisy in ("weasyprint", "fontTools"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    html = "<h1>Sample document</h1><p>Made up for the demo. Nothing here is real.</p>"
    return HTML(string=html).write_pdf()


def make_contacts() -> list[Contact]:
    contacts = []
    for index in range(50):
        first, last = FIRST[index], LAST[index % len(LAST)]
        email = f"{first}.{last}.{index:02d}@example.com".lower()
        contact, created = Contact.objects.get_or_create(
            email=email,
            defaults={
                "first_name": first,
                "last_name": last,
                "mobile": f"07700 900{index:03d}",
                "title": ["Mr", "Mrs", "Ms", "Dr", ""][index % 5],
                "home_address": "1 Example Street\nSampletown\nZZ1 1ZZ",
                "date_of_birth": date(1960 + index % 35, 1 + index % 12, 1 + index % 28),
                "ni_number": f"QQ{100000 + index * 37:06d}C" if index % 3 == 0 else "",
                "personal_utr": f"00000{index:05d}" if index % 4 == 0 else "",
                "nationality": "British",
                "country_of_residence": "United Kingdom",
            },
        )
        contacts.append(contact)
    return contacts


def seed(staff_by_email: dict[str, User]) -> dict:
    """Create the demo clients and everything on them. Returns counts for the command."""
    people = list(staff_by_email.values())
    teams = {t.name: t for t in Team.objects.all()}
    tags = {
        name: Tag.objects.get_or_create(name=name, defaults={"colour": colour})[0]
        for name, colour in [
            ("VIP", "#7c3aed"),
            ("Dormant", "#64748b"),
            ("Needs chasing", "#b45309"),
            ("Referral partner", "#0f766e"),
        ]
    }
    software = CustomFieldDefinition.objects.get_or_create(
        name="Bookkeeping software", defaults={"kind": "text", "position": 1}
    )[0]
    contacts = make_contacts()
    pdf = None
    created_clients = []

    for index, (name, client_type, status) in enumerate(CLIENTS):
        client = Client.objects.filter(name=name).first()
        if client:
            continue
        is_company = client_type in ("ltd", "plc", "llp")
        manager = people[index % len(people)]
        partner = people[(index + 1) % len(people)]
        fields = {
            "email": f"office{index:02d}@example.com",
            "phone": f"01632 960{index:03d}",
            "correspondence_address": "1 Example Street\nSampletown\nZZ1 1ZZ",
            "partner": partner,
            "team": teams.get("Compliance") if index % 4 else teams.get("Advisory"),
            "source": ["word_of_mouth", "client_referral", "website", "accountant_referral"][
                index % 4
            ],
            "payment_method": ["direct_debit", "standing_order", "bank_transfer"][index % 3],
            "custom_values": {str(software.pk): ["Xero", "QuickBooks", "FreeAgent"][index % 3]},
        }
        if is_company:
            month = [3, 6, 9, 12, 4][index % 5]
            fields.update(
                company_number=f"ZZ{100000 + index:06d}",
                company_status="active",
                incorporated_on=date(2012 + index % 10, 1 + index % 12, 1 + index % 28),
                registered_office="1 Example Street\nSampletown\nZZ1 1ZZ",
                sic_codes="62020" if index % 2 else "43220",
                nature_of_business="Made-up business for the demo",
                accounting_ref_day=28 if month == 12 else 30,
                accounting_ref_month=month,
                last_accounts_made_up_to=date(2025, month, 28 if month == 12 else 30),
                next_accounts_made_up_to=date(2026, month, 28 if month == 12 else 30),
                next_accounts_due=date(2027, (month % 12) + 1, 1),
                last_statement_made_up_to=date(2026, 2, 14),
                next_statement_made_up_to=date(2027, 2, 14),
                next_statement_due=date(2027, 2, 28),
                company_utr=f"00000{index + 100:05d}",
                vat_number=f"GB9{index:08d}" if index % 2 == 0 else "",
                vat_frequency="quarterly" if index % 2 == 0 else "",
                vat_stagger=1 + index % 3 if index % 2 == 0 else None,
                vat_scheme="standard" if index % 2 == 0 else "",
                paye_reference=f"999/AB{index:05d}" if index % 3 == 0 else "",
                payroll_frequency="monthly" if index % 3 == 0 else "",
                pay_day_rule="last_working_day" if index % 3 == 0 else "",
                employee_count=3 + index if index % 3 == 0 else None,
            )
        if client_type in ("individual", "sole_trader"):
            fields.update(mtd_start="2026-04" if index % 2 else "2027-04", payments_on_account=True)
        client = services.create_client(
            None,
            name=name,
            client_type=client_type,
            manager=manager,
            status=status,
            **fields,
        )
        if status == S.FORMER:
            _make_former(client)
        created_clients.append(client)

        main = contacts[index % 30]
        ClientContact.objects.get_or_create(
            client=client,
            contact=main,
            defaults={
                "is_main": True,
                "roles": ["director"] if is_company else ["partner"],
                "can_sign": True,
                "receives_reminders": True,
                "appointed_on": date(2020, 4, 1) if is_company else None,
            },
        )
        if index % 3:
            ClientContact.objects.get_or_create(
                client=client,
                contact=contacts[30 + index % 20],
                defaults={"roles": ["bookkeeper" if index % 2 else "shareholder"]},
            )
        if index % 5 == 0:
            ClientContact.objects.get_or_create(
                client=client,
                contact=contacts[(index + 7) % 30],
                defaults={"roles": ["director", "shareholder"], "shareholding_percent": 25},
            )
        if index % 6 == 0:
            client.tags.add(tags["VIP"])
        if status in (S.PAUSED, S.FORMER):
            client.tags.add(tags["Dormant"])
        if index % 7 == 0:
            client.tags.add(tags["Needs chasing"])
        if index % 4 == 0:
            text, pinned = SAMPLE_NOTES[index % len(SAMPLE_NOTES)]
            services.add_note(None, client, text, pinned=pinned)
        if index % 9 == 0:
            services.add_note(
                None, client, "Phoned about the next VAT return. All fine.", kind="call"
            )
        if index % 5 == 0:
            pdf = _documents(client, pdf)

    _links()
    return {
        "clients": Client.objects.count(),
        "contacts": Contact.objects.count(),
        "documents": Document.objects.count(),
        "new_clients": len(created_clients),
    }


def _make_former(client: Client) -> None:
    client.status = S.ACTIVE
    client.save(update_fields=["status"])
    owner = User.objects.filter(role__slug="owner").first()
    services.change_status(owner, client, S.FORMER, ended_on=date(2026, 3, 31))


def _documents(client: Client, pdf: bytes | None) -> bytes:
    pdf = pdf or sample_pdf()
    if client.documents.exists():
        return pdf
    services.store_document(
        None,
        client,
        SimpleUploadedFile("engagement-letter.pdf", pdf),
        category=Document.Category.ENGAGEMENT,
    )
    services.store_document(
        None,
        client,
        SimpleUploadedFile("notes.txt", b"Made-up meeting notes for the demo."),
        category=Document.Category.CORRESPONDENCE,
    )
    main = client.main_contact
    services.store_document(
        None,
        client,
        SimpleUploadedFile("proof-of-id.pdf", pdf),
        category=Document.Category.IDENTITY,
        contact=main,
    )
    return pdf


def _links() -> None:
    pairs = [
        ("Marlow & Finch Design Ltd", "Wilfred Ashby", "personal_tax"),
        ("Brightwater Plumbing Ltd", "Xanthe Brook", "personal_tax"),
        ("Copperleaf Consulting Ltd", "Dunmore Logistics Ltd", "group"),
        ("Hollin Park Estates Ltd", "Kestrel Holdings plc", "same_owner"),
        ("Yusuf Calloway", "Zara Delaney", "spouse"),
    ]
    for first, second, relationship in pairs:
        a = Client.objects.filter(name=first).first()
        b = Client.objects.filter(name=second).first()
        if a and b and not ClientLink.objects.filter(client_a=a, client_b=b).exists():
            services.add_link(None, a, b, relationship)
