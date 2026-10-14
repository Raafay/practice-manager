# Go-live checklist

**No real client data goes in until every line is ticked.** Tick a line by changing `[ ]` to `[x]`, adding your initials and the date. The owner signs off the compliance lines.

## Security

- [ ] The security review is done and every serious finding is fixed. (`docs/SECURITY-REVIEW.md`: done 14/10/2026; the owner has read the "Not fixed" list.)
- [ ] A second person, or a separate review session that did not write the code, has tried to reach another client's data through the portal and the request link and failed.
- [ ] Two-factor is on for every staff account. The development bypass code is not set. (The app refuses to start if it is.)
- [ ] HTTPS works, and the header test passes against the live site. (`python manage.py check_headers https://<your domain>`)
- [ ] Known gap accepted in writing by the owner: uploaded files are not virus scanned.

## Data

- [ ] Backups are running. A restore test has been done and recorded. (In `docs/BACKUPS.md`.)
- [ ] The file bucket is private. A direct link to a file without signing in fails.
- [ ] Encryption keys are stored somewhere safe outside the host as well.
- [ ] The retention settings are set. (Settings, Security: years to keep client records and AML records.)

## Compliance, signed off by the practice owner

- [ ] The deadline rules table in `03-services-and-deadlines.md` has been read and agreed. (In `docs/specs/`.)
- [ ] The risk questions, score bands and review intervals in `06-onboarding-and-aml.md` have been read and agreed. (In `docs/specs/`; the live ones are under Settings, Risk questions and AML bands.)
- [ ] The engagement letter, terms, privacy notice, proposal and clearance letter carry the practice's own wording.
- [ ] The practice's privacy notice mentions the portal and the companies in `SUBPROCESSORS.md`. (In `docs/`.)
- [ ] The practice's registration with the Information Commissioner's Office is current.

## Operations

- [ ] Email sending is set up with SPF, DKIM and DMARC, and a test message arrives in an inbox, not in spam.
- [ ] The Companies House key works: `ch_check` returns dates for a known company. (`python manage.py ch_check <company number>`)
- [ ] Xero is connected and a sync has run.
- [ ] The worker is running and last night's jobs show as done. (Settings, System.)
- [ ] Every reminder schedule is still off. The owner switches them on one at a time after go-live.
- [ ] The staff have read the staff guide and signed in. (`docs/STAFF-GUIDE.md`)

## Moving across

- [ ] Run both systems side by side for at least one full month before cancelling BrightManager.
- [ ] Import clients, contacts and services from the BrightManager export. Use the migration helper to clear deadlines already dealt with.
- [ ] Compare the next 60 days of deadlines in both systems, client by client. Any difference is looked into before relying on the new one.

---

Signed off by the practice owner: ______________________  Date: ____________
