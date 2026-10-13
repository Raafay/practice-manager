# 02 Clients and contacts

Read by Stage 2. Stage 3 reads section 2 for the company fields.

## 1. Client

One table holds prospects, live clients and former clients. The `status` field tells them apart.

Status values and how a client moves between them:

- `prospect`: an enquiry that has not signed. Becomes `onboarding` when a proposal is accepted or staff change it. Becomes `lost` if it goes nowhere.
- `onboarding`: signed, checklist in progress. Becomes `active` through the onboarding gate (Stage 7).
- `active`: a live client.
- `paused`: still a client, work on hold.
- `former`: the relationship has ended. Sets `relationship_ended_on` and `retain_until`.
- `lost`: a prospect that did not sign.

In Stage 2 a manager or the owner can change status by hand. Later stages add the proper routes.

Client types: Private limited company, Public limited company, Limited liability partnership, Partnership, Sole trader, Individual, Trust, Charity, Other.

## 2. Client fields, grouped as the panels on the Info tab

Required information

- name (required), client type (required), status
- client reference: made automatically as C0001, C0002 and so on, editable
- partner (staff user, optional), manager (staff user), team (optional)

Company details (shown for company types)

- company number, company status, incorporated on
- registered office address, SIC codes, trading name, nature of business
- accounting reference day and month
- last accounts made up to, next accounts made up to, next accounts due
- last statement made up to, next statement made up to, next statement due
- Companies House authentication code (encrypted)
- last synced at

The filing dates are filled by the Companies House sync in Stage 3 and are read-only once a company number is set.

Tax and registration

- company UTR (encrypted), VAT number, VAT registered on, VAT frequency (monthly, quarterly, annual), VAT stagger (1: quarters ending March, June, September, December. 2: January, April, July, October. 3: February, May, August, November), VAT scheme (standard, flat rate, cash, annual accounting)
- PAYE reference, Accounts Office reference, payroll frequency (weekly, fortnightly, four-weekly, monthly), pay day rule (a day of the month, last working day, last Friday, or a weekday for weekly pay), first pay date, number of employees
- CIS role (none, contractor, subcontractor, both)
- pension provider, auto-enrolment duties start date, last re-enrolment date
- for individuals and sole traders: Making Tax Digital for Income Tax start (not in scope, April 2026, April 2027, April 2028), payments on account (yes or no)

Contact details

- email, phone, website, correspondence address

Internal

- source (word of mouth, client referral, accountant referral, website, other), referred by (another client, or free text)
- client since, relationship ended on, retain until
- tags, custom fields (name and value pairs the practice defines in Settings)
- payment method (standing order, Direct Debit, bank transfer, card, other)
- "do not send automatic messages" switch
- Xero contact id (set in Stage 11)
- request link token (used in Stage 10)

## 3. Contacts

Contact (a person): title, first name (required), middle name, last name (required), preferred name, email, mobile, phone, date of birth, National Insurance number (encrypted), personal UTR (encrypted), home address, nationality, country of residence, occupation, notes, Companies House officer id, Companies House personal code (encrypted), identity verified with Companies House (yes or no, and date).

ClientContact (the link between a person and a client):

- roles, more than one allowed: main contact, director, secretary, shareholder, person with significant control, partner, member, trustee, employee, bookkeeper, other
- is main contact. Exactly one per client.
- receives reminders, can sign, portal access
- appointed on, resigned on, shareholding percent (optional)
- source: added by hand or from Companies House

Rules:

- A person exists once. Adding a contact searches existing contacts by email and by name first and offers to link.
- Removing a link never deletes the person.
- "Create personal tax client" on a contact makes a new client of type Individual with that person as main contact, and links the two clients.

## 4. Client links

ClientLink: two clients and a relationship (director's personal tax, group company, same owner, spouse or partner, other) with a note. Shown on both clients.

## 5. Notes and documents

Note: client, text, author, pinned. Notes appear on the timeline. Pinned notes also show at the top of the Info tab.

Document: client, contact (optional), category, title, file, original name, size, type, sensitive, shared with portal, uploaded by, source (staff, portal, request, system), deleted at.

Categories: Identity, Proof of address, Engagement, Accounts, Tax, VAT, Payroll, Bookkeeping, Correspondence, Advisory, Other. Identity and Proof of address are sensitive by default.

The Documents tab lists by category with search, drag-and-drop upload, rename, change category, mark sensitive, share with portal (Stage 10) and delete. File rules are in `01-security-and-users.md` section 7.

## 6. Client list

Default columns: name with status badge, type, manager, partner, next deadline (Stage 4), monthly fee (Stage 4, only with `fees.view`), year end, tags.

- Column chooser. Sort on any column. 50 rows a page.
- Filters: status (default active, onboarding and paused), type, manager, partner, team, tag, service (Stage 4), has an overdue deadline (Stage 4).
- Search box: name, trading name, company number, contact name, email.
- Saved views: a name plus the current filters, columns and sort. Private or shared with everyone.
- Export the current view to CSV. Needs `data.export`. Logged.
- "New client" opens a short form: name, type, manager, main contact. Stage 3 adds "Add from Companies House".

Prospects and lost prospects are left out of this list. They live under Prospects (Stage 9). Until then, a status filter can show them.

## 7. Client page

Header: name, status badge, type, client reference, company number with a "View on Companies House" link. Badges for portal state and AML state arrive in Stages 9 and 10.

Buttons, added as their stages arrive: New task (5), Log time (11), Send email and Send SMS (7), Add note (2), and a More menu with Change status (2), Archive (2), Send to Xero (11).

Tabs, each added by the stage shown:

| Tab | Shows | Stage |
|---|---|---|
| Info | The panels in section 2, plus Services on the right | 2, services in 4 |
| Timeline | Every event for this client, newest first, with a filter by type and "Add note" and "Log a call" | 2 |
| Contacts | People linked to this client, their roles and switches | 2 |
| Links | Related clients | 2 |
| Documents | Files by category | 2 |
| Companies House | Profile, officers, owners, filing history, sync state | 3 |
| Deadlines | Open and past deadlines | 4 |
| Tasks | This client's tasks | 5 |
| Onboarding | Checklist and the go-live button | 9 |
| Engagement | Proposals and engagement letters | 8, 9 |
| Risk | AML assessment, identity checks, review dates | 9 |
| HMRC | Agent authorisations | 9 |
| Requests | Requests from this client and the request link | 10 |
| Time | Time logged | 11 |
| Fees and invoices | Agreed fees and Xero invoices | 11 |

Info tab behaviour:

- Two columns on a wide screen. Left: the panels, each folding, each with its own Edit button. Edit swaps the panel for a form in place (HTMX) with Save and Cancel.
- Which panels are folded is remembered per user in the browser.
- Panels that do not apply to the client type are hidden. A sole trader has no Company details panel.
- The Main contact panel shows the main contact's name, email and phone with a link to the full contact, and the "Create personal tax client" action.

## 8. Search

The search box in the top bar looks up clients as you type, after two characters. It matches name, trading name, company number, contact name and email. Each result shows the status badge when the client is not active: Prospect, Onboarding, Paused, Former, Lost. Enter opens a full results page. The `/` key puts the cursor in the box.

## 9. Archive and delete

- Archive hides a client from lists. It asks for a reason and is logged. An archived client can be restored.
- Delete for good needs `clients.delete`, asks for the client name to be typed, is blocked while a retention period runs, and is logged.
