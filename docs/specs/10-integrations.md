# 10 Outside services

Stage 3 reads sections 1 and 2. Stage 11 reads section 3. Stage 13 reads sections 4 to 6.

Cloud sessions cannot reach any of these services. Build each client against sample responses saved under `apps/<app>/tests/samples/`, written from the shapes below with made-up names and numbers. Keep every outside call behind one small class so it can be swapped for a fake in tests.

The shapes below are written from knowledge of the public APIs as of October 2026. The live service is the authority. Clients must cope with missing and extra fields, and the first live check may need small fixes.

## 1. Companies House

- Base address: `https://api.company-information.service.gov.uk`
- Sign-in: HTTP Basic, with the API key as the user name and an empty password.
- The key is free. It comes from `developer.company-information.service.gov.uk` by registering an application and creating a REST API key for the live environment. Stored in the environment as `COMPANIES_HOUSE_API_KEY`.
- Limit: 600 requests in any five minutes for each key. Response headers `X-Ratelimit-Remain` and `X-Ratelimit-Reset` say where you stand. A 429 means stop and wait.
- Stay under two requests a second. On 429 wait until the reset time. On a 5xx retry three times with a growing wait.

Calls used:

| Call | For |
|---|---|
| `GET /search/companies?q={text}&items_per_page=10` | Finding a company by name |
| `GET /company/{number}` | Profile and filing dates |
| `GET /company/{number}/officers` | Directors and secretaries |
| `GET /company/{number}/persons-with-significant-control` | Owners with significant control |
| `GET /company/{number}/filing-history?items_per_page=25` | Recent filings |

Company numbers are eight characters. Pad numbers with leading zeros. Some start with letters, such as SC or NI.

Profile, the fields used:

    {
      "company_name": "EXAMPLE TRADING LTD",
      "company_number": "09999901",
      "company_status": "active",
      "type": "ltd",
      "date_of_creation": "2015-03-12",
      "registered_office_address": {
        "address_line_1": "1 Example Street", "address_line_2": "Suite 2",
        "locality": "Bradford", "region": "West Yorkshire",
        "postal_code": "BD1 1AA", "country": "England"
      },
      "sic_codes": ["47910"],
      "accounts": {
        "accounting_reference_date": {"day": "31", "month": "03"},
        "last_accounts": {"made_up_to": "2025-03-31", "period_start_on": "2024-04-01", "period_end_on": "2025-03-31", "type": "micro-entity"},
        "next_accounts": {"period_start_on": "2025-04-01", "period_end_on": "2026-03-31", "due_on": "2026-12-31", "overdue": false},
        "next_made_up_to": "2026-03-31",
        "next_due": "2026-12-31",
        "overdue": false
      },
      "confirmation_statement": {
        "last_made_up_to": "2025-10-20",
        "next_made_up_to": "2026-10-20",
        "next_due": "2026-11-03",
        "overdue": false
      },
      "has_charges": false,
      "has_insolvency_history": false,
      "etag": "a1b2c3"
    }

A new company has no `last_accounts.made_up_to`. A dissolved company has `company_status` of `dissolved` and may lack the accounts block.

Officers, one item:

    {
      "name": "SMITH, Jane Anne",
      "officer_role": "director",
      "appointed_on": "2015-03-12",
      "resigned_on": "2024-01-31",
      "date_of_birth": {"month": 6, "year": 1980},
      "nationality": "British",
      "occupation": "Director",
      "country_of_residence": "England",
      "address": {"address_line_1": "1 Example Street", "locality": "Bradford", "postal_code": "BD1 1AA"},
      "links": {"officer": {"appointments": "/officers/AbCdEf123/appointments"}}
    }

`resigned_on` is present only for people who have left. The id in `links.officer.appointments` identifies the person across companies. Names come as "SURNAME, Forenames". Corporate officers have a role such as `corporate-director` and no date of birth.

Persons with significant control, one item:

    {
      "name": "Mrs Jane Anne Smith",
      "name_elements": {"title": "Mrs", "forename": "Jane", "middle_name": "Anne", "surname": "Smith"},
      "kind": "individual-person-with-significant-control",
      "natures_of_control": ["ownership-of-shares-75-to-100-percent"],
      "notified_on": "2016-04-06",
      "date_of_birth": {"month": 6, "year": 1980},
      "nationality": "British",
      "country_of_residence": "England"
    }

`ceased_on` is present for former owners. Other kinds exist for companies and legal persons.

Filing history, one item:

    {
      "category": "accounts",
      "type": "AA",
      "date": "2025-11-02",
      "description": "accounts-with-accounts-type-micro-entity",
      "description_values": {"made_up_date": "2025-03-31"},
      "transaction_id": "MzQ1Njc4OWFkaXF6a2N4"
    }

A confirmation statement has category `confirmation-statement` and type `CS01`.

Search, one item: `title`, `company_number`, `company_status`, `company_type`, `date_of_creation`, `address_snippet`.

Since 18 November 2025 directors and owners must verify their identity with Companies House, and a company cannot file its confirmation statement unless every director has given a personal code. The officer and owner responses may carry identity verification fields. If they are present on the live service, store and show them. Either way the contact record has a place for the personal code (encrypted) and a verified flag that staff can set.

Adding a company

1. Staff type a name or number. The app shows up to ten matches.
2. Picking one shows a preview: name, number, status, type, address, filing dates, officers and owners.
3. Confirming creates the client (or fills in an existing one), creates a contact for each current officer and owner who is a person, and links them with roles. An existing contact is matched by the Companies House officer id, then by name with birth month and year.

The sync

- A job runs every night at 02:00 for every client with a company number whose status is prospect, onboarding, active or paused.
- It fetches the profile. If the `etag` changed, or it is Sunday, it also fetches officers, owners and filing history.
- It updates the client's company fields and writes a timeline event for each change: filing dates, a new filing, status, registered office, name, an officer appointed or resigned, an owner added or ceased.
- A status other than `active` raises a notification to the manager.
- An officer who has left is marked resigned on the link. Nobody is deleted.
- It then asks the deadline job to run for that client (Stage 4 onward).
- "Sync now" on the client Companies House tab does the same for one client.

The Companies House tab shows: the profile as held, when it was last synced, officers, owners, the last 25 filings, and a "View on Companies House" link to `https://find-and-update.company-information.service.gov.uk/company/{number}`.

A management command `ch_check <number>` makes one live profile call and prints the filing dates. It is for the first live test once a key exists.

## 2. Background jobs

The `jobs` app, built in Stage 3 and used by every later stage.

- A registry of named jobs, each with a schedule: every so many minutes, or daily at a time, or weekly on a day and time.
- JobRun: job name, started at, finished at, state (running, done, failed), message, counts.
- `manage.py worker` loops for ever: each minute it runs whatever is due. A row lock stops two workers running the same job.
- `manage.py run_job <name>` runs one job now.
- A page for the owner lists jobs, their last run and result, with "Run now".
- A job that fails notifies the owner and is tried again at its next slot.
- Jobs must be safe to run twice.

Jobs by stage: Companies House sync and bank holiday refresh (3), deadline creation (4), task creation (5), repeating tasks and the daily email (6), reminder schedules and the send queue (7), quiet-prospect check (8), AML and expiry checks (9), Xero sync and the owner summary (11), retention report (13).

Bank holidays: in production a monthly job reads `https://www.gov.uk/bank-holidays.json`, takes the `england-and-wales` list, and updates the stored dates. If the call fails, the bundled list stays in use.

## 3. Xero

- A standard web app using OAuth 2.0 with the authorisation code flow. The owner connects the practice's own Xero organisation once, from Settings, Integrations.
- Xero's developer pricing in October 2026 has a free Starter tier with up to 5 connections and 1,000 calls a day for each organisation. That is enough here. Check `developer.xero.com/pricing` when registering the app.
- Apps created since 2 March 2026 must ask for the newer, narrower scopes. Expect to need: `offline_access`, `accounting.contacts`, `accounting.invoices.read`, `accounting.payments.read`. Check Xero's current scope list before building the consent address, and ask for the narrowest set that works.
- Addresses: authorise at `https://login.xero.com/identity/connect/authorize`, tokens at `https://identity.xero.com/connect/token`, list of connected organisations at `https://api.xero.com/connections`, accounting data under `https://api.xero.com/api.xro/2.0/`.
- Every data call sends the organisation id in the `xero-tenant-id` header.
- Access tokens last 30 minutes. Refresh tokens last 60 days and change on every use. Store both encrypted. Refresh inside a database lock so two processes cannot use the same refresh token. The nightly sync keeps the connection alive.
- Limits: 60 calls a minute and 5 at once for each organisation, plus the daily limit above. On 429 obey the `Retry-After` header.
- Environment: `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`. The redirect address is `{site}/integrations/xero/callback`.

Calls used:

| Call | For |
|---|---|
| `GET Contacts` | Customers, for matching to clients |
| `POST Contacts` | "Send to Xero" |
| `GET Invoices?where=Type=="ACCREC"&page=N` with `If-Modified-Since` | Sales invoices changed since the last sync |
| `GET CreditNotes?where=Type=="ACCRECCREDIT"` with `If-Modified-Since` | Sales credit notes |

Invoice, the fields used:

    {
      "InvoiceID": "0f4a3c1e-0000-4000-8000-000000000001",
      "Type": "ACCREC",
      "InvoiceNumber": "INV-0101",
      "Reference": "October fee",
      "Contact": {"ContactID": "7c1f0000-0000-4000-8000-000000000002", "Name": "Example Trading Ltd"},
      "DateString": "2026-10-01T00:00:00",
      "DueDateString": "2026-10-15T00:00:00",
      "Status": "AUTHORISED",
      "SubTotal": 300.00,
      "TotalTax": 60.00,
      "Total": 360.00,
      "AmountDue": 360.00,
      "AmountPaid": 0.00,
      "AmountCredited": 0.00,
      "CurrencyCode": "GBP",
      "UpdatedDateUTC": "/Date(1790000000000+0000)/"
    }

States: DRAFT, SUBMITTED, AUTHORISED, PAID, VOIDED, DELETED. Dates may arrive as the `DateString` form or as `/Date(milliseconds+0000)/`. Parse both.

Stored locally: XeroConnection (organisation id and name, tokens, expiry, connected by, last sync), XeroContact (id, name, email, linked client, match state), XeroInvoice and XeroCreditNote (the fields above), and a sync log.

The sync runs nightly and on "Sync now". It reads only. The one write is creating a contact when staff press "Send to Xero".

If the connection breaks, the Finance pages say so with the date of the last good sync, and the owner is notified.

## 4. Email

Sent through Django's email system with django-anymail, so the provider is a setting.

- `EMAIL_PROVIDER`: `console` in development, `memory` in tests, and the chosen provider in production.
- `DEFAULT_FROM_EMAIL`: the practice's sending address.
- Stage 13 picks the provider, proves ownership of the domain with DNS records (SPF, DKIM and DMARC), and wires the delivery webhook.

Things to weigh when choosing: a UK or EEA data region or a UK transfer safeguard, cost at low volume, delivery reports, and whether anymail supports it. Amazon SES in the London region, Postmark and Brevo are all supported.

## 5. Text messages

Interface only in the first version. See `07-communications.md` section 7.

## 6. Not connected in the first version

- HMRC's Agent Authorisation API. HMRC reviews software before granting live access. Requests are tracked by hand until then.
- A paid identity-check service.
- WhatsApp Business, which needs a Meta business account, verification and a dedicated number, and charges per template message.
- Receiving email.
- Slack or Teams.
