# Registering the Xero app

The live connection can only be made once the site is deployed, or on a laptop with the redirect address set to localhost. Cloud sessions cannot reach Xero.

1. Sign in at developer.xero.com with the practice's Xero login and open My Apps, then New app.
2. Name it (for example "Practice Manager"), choose "Web app", and give the company or application URL.
3. Redirect URI: `{SITE_URL}/integrations/xero/callback`, for example `https://pm.example.co.uk/integrations/xero/callback`. For a laptop use `http://localhost:8000/integrations/xero/callback` and set `SITE_URL=http://localhost:8000`.
4. Create the app, then Configuration, Generate a secret. Copy the client id and the secret.
5. Put them in the server's environment as `XERO_CLIENT_ID` and `XERO_CLIENT_SECRET`, then restart the site. Never commit them.
6. Sign in as the owner, open Settings, Integrations, and press Connect Xero. Choose the practice's organisation and allow access.
7. The scopes asked for are `offline_access accounting.contacts accounting.invoices.read accounting.payments.read`. Check Xero's current scope list when registering; apps created since 2 March 2026 must use the narrower ones.
8. The first sync starts within a minute (the worker must be running). Then open Finance, Xero contacts and confirm each match.
