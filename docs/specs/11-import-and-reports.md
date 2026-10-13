# 11 Import and reports

Read by Stage 12.

## 1. Why the import matters

The practice's clients live in BrightManager. Moving them by hand would take days and invite mistakes. BrightManager can export lists to CSV, but we do not yet know its column headings, so the import must let the owner match columns on screen.

Only the owner can import (`data.import`). No real client file is loaded until the Stage 13 go-live checklist has passed. Build and test with made-up files.

## 2. The import wizard

Under Settings, Import. Three kinds of file: clients, contacts, and services with fees.

Steps:

1. Upload a CSV. Detect the delimiter and the encoding. Accept a UTF-8 byte order mark. Show the first ten rows.
2. Match columns. Each column in the file gets a drop-down of fields it can fill, or "Ignore". Suggest matches from the header text. Let the owner save the matching under a name, such as "BrightManager clients", and reuse it.
3. Check. Show a count of rows that will be created, rows that will update an existing record, rows with problems, and the problems row by row. Nothing is saved yet.
4. Import. Save the good rows inside one database transaction. Show a summary and offer a CSV of the rows that failed with the reason for each.

Fields a file can fill:

- Clients: name, type, status, client reference, company number, manager (by name or email), partner, email, phone, address lines, postcode, VAT number, VAT frequency, VAT stagger, PAYE reference, Accounts Office reference, year end, UTR, client since, source, tags, notes.
- Contacts: client (by reference, company number or name), title, first name, last name, email, mobile, phone, date of birth, role, is main contact, receives reminders.
- Services and fees: client (by reference, company number or name), service (by name or code), fee, frequency, start date.

Matching an existing record:

- Clients: by client reference, then company number, then exact name without regard to case.
- Contacts: by email, then by full name within the same client.
- A match updates only the empty fields unless the owner ticks "overwrite".

Cleaning:

- Trim spaces. Pad company numbers to eight characters. Read dates as dd/mm/yyyy, and also yyyy-mm-dd.
- Money: accept a pound sign and commas.
- Client type and other fixed lists: match common spellings, such as "Limited Company" and "Ltd". Unrecognised values are a problem to fix, not a guess.
- Yes and no columns: accept yes, y, true, 1, on.

Records:

- ImportRun: kind, file name, who, when, the matching used, counts, state.
- Every record created by an import is tagged with its run.
- "Undo this import" deletes records the run created that nobody has changed since. It lists what it could not undo.
- The run is written to the audit log.

After a client import:

- Offer "Fetch from Companies House" for every imported client with a company number. This runs the sync in the background with progress.
- Imported clients arrive with status `active` unless the file says otherwise, with no onboarding checklist and an AML state of "needs review".

Migration helper, under Settings, Import: after services are imported and deadlines created, list every open deadline that is already overdue or due within 30 days, grouped by rule, with tick boxes and "Mark as already done". This clears history that was dealt with in BrightManager.

## 3. Reports

Under Reports. Each has filters, a table on screen, and CSV export with `data.export`. Exports are logged.

| Report | Shows | Stage it first appears |
|---|---|---|
| Deadlines | Open deadlines across the practice | 4 |
| Tasks | Tasks by state, owner, client, kind, dates. Completed work in a date range. | 12 |
| Client list | Chosen columns for chosen clients | 2 |
| Services | Which clients take which services, with fees for `fees.view` | 12 |
| AML register | Level, state, review dates, identity progress | 9 |
| Time | Hours by client, person, service and month | 12 |
| Requests | Volume, time to first action, time to close, by client and channel | 12 |
| Pipeline | Prospects by stage, source and outcome, won and lost reasons | 12 |
| Communications | Messages sent, failed and bounced, by template | 12 |

Client summary: a PDF for one client with its details, contacts, services, open deadlines, open tasks and recent activity. Offered as "Generate report" on the client page. Fees appear only if the person generating it has `fees.view`.

## 4. Tests

- A clients file with clean rows, a duplicate, a bad date and an unknown type gives the right counts and the right messages.
- Company numbers are padded. Dates in both formats are read.
- A saved matching is offered when the same headers appear again.
- Undo removes untouched records and keeps changed ones.
- A file with a formula in a cell is exported back with the cell made safe (prefix with a quote mark) so a spreadsheet will not run it.
- Every export respects `fees.view` and leaves out sensitive documents and encrypted values.
