# 06 Onboarding, engagement letters, AML and HMRC authorisations

Read by Stage 7.

The practice's rule: a client is onboarded and through its anti-money-laundering checks before any work starts. The app enforces that with a gate.

The practice owner must read section 4 before go-live. The practice is responsible for its own AML policy. The app records what was done. It does not decide for the practice.

## 1. Onboarding checklist

OnboardingItem: client, key, name, needed before go-live (yes or no), state (to do, in progress, done, not needed), done on, done by, note, set by the system (yes or no).

A checklist is created when a client's status becomes `onboarding`. The template is edited in Settings. Seed:

| Key | Item | Needed before go-live | Ticked by |
|---|---|---|---|
| proposal_accepted | Proposal accepted | no | the system |
| engagement_letter_signed | Engagement letter signed | yes | the system |
| client_details | Client details form completed | yes | the system (Stage 10) or staff |
| identity_verified | Identity verified for everyone who needs it | yes | the system |
| risk_assessment_approved | Risk assessment approved | yes | the system |
| professional_clearance | Clearance from the previous accountant | no | staff |
| hmrc_authorisations | HMRC agent authorisations in place | no | the system |
| companies_house_code | Companies House authentication code held | no | staff |
| software_access | Access to the client's accounting software | no | staff |
| payment_set_up | Payment method set up | no | staff |
| services_confirmed | Services, fees and start dates confirmed | yes | staff |
| welcome_sent | Welcome message sent | no | staff |

The client Onboarding tab shows the checklist with progress and one button, "Make live".

- The button works when every item needed before go-live is done or not needed.
- Making live sets status `active`, sets "client since", turns `proposed` services into `active` with their start dates, creates deadlines, and logs it.
- A user with `onboarding.override` can make a client live early. A written reason is required and is logged as an override.

Clients brought in by the import (Stage 12) skip the gate. They arrive `active` with an AML state of "needs review", so the gaps show on the AML register without blocking work.

## 2. Engagement letter

Parts, edited in Settings as rich text: a covering letter, one schedule per service (the service's engagement schedule text), standard terms, and a privacy notice. Merge fields as in `07-communications.md`.

EngagementLetter: client, version, state (draft, sent, viewed, signed, replaced), frozen copies of the services and fees, the full text as sent, unsigned PDF, signed PDF, sent at, signed at, signer (contact), typed name, IP address, browser, document fingerprint (SHA-256 of the unsigned PDF), review due (12 months after signing by default).

Flow:

1. Staff press "Prepare engagement letter". The app builds it from the parts and the client's services, and shows a preview that can be edited.
2. Sending freezes the text, makes the PDF with WeasyPrint, and emails the signer an action link through the queue.
3. The signing page shows the letter, a PDF download, a tick box "I have read and agree to this letter", and a box to type the full name.
4. On signing, the app makes the signed PDF: the letter plus a final page stating who signed, their email, the time in UK time and UTC, the IP address and the fingerprint. It saves the PDF to Documents under Engagement, ticks the checklist item, emails the client a copy and notifies staff.

The letter goes out in the practice's name. There is no second signature step for the practice.

Changing a client's services later offers "Prepare a new engagement letter". The old one is marked replaced when the new one is signed. Thirty days before a review date, a task is created for the manager.

The client Engagement tab lists proposals and engagement letters with their states.

Seed placeholder wording only, with a banner on every seeded part: "Starter text. Replace with the practice's own wording before use." Engagement letters are legal documents and the practice's professional body publishes model wording.

## 3. Who must be identified

For each client the app proposes a list of people from the contact roles:

- the main contact
- every director, partner, member or trustee
- every owner with more than 25% (people with significant control from Companies House)

Staff can add or remove a person with a reason.

IdentityCheck: client, contact, state (not started, requested, received, verified, failed, expired), method (original seen in person, Post Office certified copy, copy certified by a professional, electronic check, other), document type (passport, driving licence, national identity card, other), document expiry, proof of address type, verified by, verified at, notes, and links to the uploaded documents.

- Document numbers are not stored. The upload is the record.
- Uploads go to Documents under Identity or Proof of address and are sensitive.
- 60 days before a document expires, the manager gets a notification. The check does not lapse by itself. Staff decide.
- The checklist item is ticked when every listed person is verified.

A "Complete credit check" or electronic identity check through a paid service is not in the first version. Build the method list and a small `IdentityProvider` interface so one can be added.

## 4. Risk assessment

RiskQuestion: section, text, help text, answer type (yes or no, or a choice), a score for each answer, "means enhanced checks" flag, order, active. Edited in Settings with `settings.manage`. Every change is logged.

RiskAssessment: client, version, state (draft, submitted, approved, sent back), answers (question, answer, note), score, suggested level, level (low, medium, high), reason if the level differs from the suggestion, enhanced checks needed, enhanced checks notes, assessed by, assessed at, approved by, approved at, next review due, summary.

Scoring:

- The score is the sum of the answer scores. Suggested level: 0 to 4 low, 5 to 9 medium, 10 or more high. The thresholds are settings.
- Any answer flagged "means enhanced checks" makes the suggestion high and requires the enhanced checks notes to be filled in: what extra evidence was obtained, source of funds and wealth, and approval by the owner.
- The assessor can set a higher level freely. Setting a lower level than suggested needs a reason.
- Approval needs `aml.approve`. If the level is high and another approver exists, the approver cannot be the assessor.
- On approval the app saves a snapshot of the Companies House profile, officers and owners to Documents, sets the next review date, and ticks the checklist item.

Seed questions, in plain words. Scores in brackets for the answer that raises risk.

The client

- Have we met the client face to face, or verified them another reliable way? (No: 2)
- Is the client acting on behalf of someone else who has not been identified? (Yes: 5, enhanced)
- Has the client been unusually secretive, evasive or in a hurry? (Yes: 3)
- Was the client turned away by, or did they leave, a previous accountant in unclear circumstances? (Yes: 2)

Ownership

- Is the ownership structure complex or hard to follow? (Yes: 3)
- Have all owners with more than 25% been identified? (No: 5, enhanced)
- Does any owner or director live outside the UK? (Yes: 2)

Geography

- Does the client have owners, customers, suppliers or funds linked to a high-risk country on the UK government's list? (Yes: 5, enhanced)

The business

- Does the business handle a lot of cash? (Yes: 3)
- Is the business in a higher-risk sector, for example money transfer, crypto assets, gambling, scrap metal, used cars, property, or precious metals and stones? (Yes: 3)
- Do the turnover and activity we see fit what the client told us? (No: 4)

People

- Is the client, an owner or a close relative or associate a politically exposed person? (Yes: 5, enhanced)
- Did a check against the UK sanctions list find a match? (Yes: 10, enhanced. The help text tells staff to stop and speak to the owner.)
- Is there negative news about the client or its owners that bears on honesty? (Yes: 3)

Our service

- Will we hold or move client money? (Yes: 3)
- Are we forming companies or providing a registered office or director services? (Yes: 2)
- Does the work involve tax planning that is aggressive or unusual? (Yes: 3)

The sanctions and politically-exposed answers also record the date checked and how. There is no automatic screening in the first version.

## 5. Ongoing review

- Next review due is the approval date plus an interval by level: high 12 months, medium 24, low 36. These are settings.
- 30 days before it falls due, a task "AML review: {client}" is created for the manager, category AML.
- A review is also prompted when the Companies House sync sees a change of owner or director, when a higher-risk service is added, or when a client is reactivated.
- A review is a new version of the assessment, starting from the previous answers.

AML state on the client header, worked out: not started, in progress, awaiting approval, approved, review due, review overdue, needs review (imported).

AML register, under Reports: every client with level, state, last assessed, next review, identity check progress. Filters and CSV export for the owner.

Practice records, under Settings: the name of the supervisory body, the nominated officer (a staff user), a log of staff AML training (person, date, course, notes) with a reminder after 12 months, and a small library for the practice's policy documents.

Reports of suspicious activity are not stored in this app.

Retention: AML records are kept until the client's "retain until" date, five years after the relationship ends.

## 6. HMRC agent authorisations

The client HMRC tab. One row per tax.

AgentAuthorisation: client, tax (Self Assessment, Corporation Tax, PAYE, VAT, CIS, Making Tax Digital for VAT, Making Tax Digital for Income Tax, other), contact (for personal taxes), method (code by post, digital handshake link, paper form 64-8, already held), state (not started, requested, code received, submitted, authorised, expired, rejected), requested on, code (encrypted), code received on, code expires on, link sent on, link expires on, authorised on, notes.

- A digital handshake link expires 21 days after it is created. Fill "link expires on" from that.
- A postal code is taken to expire 30 days after it is issued. The date can be edited. (Confirm the 30 days with the practice.)
- Seven days before either expiry the manager is notified, and the item shows on the Overview.
- When every tax the client's services need is authorised, the checklist item is ticked. Which taxes a service needs: Self Assessment needs SA, CT600 needs CT, Payroll needs PAYE, VAT needs VAT or MTD VAT, CIS needs CIS, MTD for Income Tax needs MTD Income Tax.

A direct link to HMRC is not in the first version.

## 7. Professional clearance

ClearanceRequest: client, previous accountant (name, firm, email), sent on, chased on, reply received on, notes, and a short list of what was asked for (last accounts, tax returns, trial balance, payroll records, VAT workings) with tick boxes for what arrived.

A letter template goes through the queue as an email with a PDF copy. A chase is offered after 14 days.

## 8. Tests

- The gate: blocked with a needed item open, allowed when all are done, override needs the right and a reason.
- Scoring: low, medium and high cases, the enhanced flag, a lower level needing a reason, the assessor not approving their own high-risk assessment.
- Signing: the signed PDF exists, the fingerprint matches the unsigned PDF, the link cannot sign twice.
- Identity documents are sensitive and each view is logged.
- Expiry dates for both authorisation methods.
- A portal or public user cannot reach any of these pages for another client.
