# Outside companies that hold or see client data

Every outside company that stores or sees the practice's client data through this app. Mention these in the practice's privacy notice (the go-live checklist asks for this). Update this file when a hosting company is chosen or anything changes.

| Company | What it is for | What it holds or sees | Where | Status |
|---|---|---|---|---|
| **The hosting company** (to be chosen; see `docs/DEPLOY.md`) | Runs the app, the database and the backups | Everything in the app: clients, contacts, tax references (encrypted), tasks, messages, the activity log | UK or EEA region (required) | **Fill in once chosen** |
| **The file storage company** (often the same as the host) | The private bucket for uploaded files | Every uploaded file: identity documents, records, signed letters | UK or EEA region (required) | **Fill in once chosen** |
| **Amazon Web Services (Amazon SES)**, unless Postmark or Brevo is chosen | Sending email to clients and staff | Each email's addresses, subject and content; delivery and bounce reports | London (eu-west-2) | Default choice |
| **Companies House** (UK government) | Company details, officers and filing dates | Searches for company numbers. Nothing is sent to it except the company number | UK | Public register; read only |
| **Xero** | Reading invoices and payments; creating a contact when asked | Client names, Xero contact details, invoice figures. Xero already holds the practice's accounts | Xero's data centres (see Xero's own list) | When connected |
| **Sentry** (optional; only if `SENTRY_DSN` is set) | Error reports | Error type, file and line, and the address with tokens removed. No request data, user details or error text | Choose the EU region | Off unless set |
| **GitHub** | Holds the code | Code only. No client data: the repository holds only made-up demo data | US | |
| **gov.uk** | Bank holiday dates | Nothing is sent | UK | |

Not used in the first version: AI services (DECISIONS 10), text message providers, identity-check services, HMRC's API, WhatsApp, Slack or Teams.

Staff use their own devices and an authenticator app (such as Microsoft Authenticator or Google Authenticator). The authenticator app holds a secret for signing in but no client data.
