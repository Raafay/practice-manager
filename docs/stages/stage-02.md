# Stage 2: Clients and contacts

Goal: staff can add, find and open clients, and a client page holds its details, people, related clients, documents and history.

Read first: `docs/specs/02-clients.md`, `docs/reference/bright-observed.md` sections 1 and 2.

## Build

1. Models in `apps/clients`: `Client`, `Contact`, `ClientContact`, `ClientLink`, `Note`, `Tag`, `CustomFieldDefinition`, `Document`, `SavedView`. Fields as in the spec, sections 1 to 5. Encrypted fields where the spec says. `public_id` on Client, Contact and Document.

2. Client list page with columns, column chooser, sort, filters, search, saved views and CSV export, as in section 6. "New client" form.

3. Client page.
   - Header with name, status badge, type, reference and company number.
   - Buttons that exist now: Add note, and More with Change status and Archive.
   - Tabs: Info, Timeline, Contacts, Links, Documents. Each tab loads with HTMX and has its own address.
   - Info tab with the panels in section 2, each folding and each edited in place. Hide panels that do not apply to the client type. Leave the right-hand column empty for Stage 4.

4. Contacts.
   - Contacts tab: list with roles and switches, add (search existing people first), edit, unlink.
   - One main contact per client, enforced.
   - A contact page showing the person and every client they are linked to.
   - "Create personal tax client".
   - Sensitive fields masked with a logged "Show".

5. Links tab: add and remove related clients.

6. Documents tab and file handling exactly as in `01-security-and-users.md` section 7 (read only that section): upload, categories, sensitive flag, private storage, permission-checked download, preview for PDFs and images, access logging, soft delete.

7. Timeline tab: the client's events newest first, filter by type, "Add note", "Log a call". Make sure every change made in this stage writes an event with a readable sentence.

8. Search in the top bar, as in section 8, and a full results page.

9. Status changes by hand for managers and the owner, with the rules in section 1. Archive and restore with a reason. Delete for good, with the checks in section 9.

10. Settings: Tags, and Custom fields.

11. Demo data: 30 made-up clients across every type and status, 50 contacts, some shared between clients, a few links, notes and small sample documents.

## Checks

- `make lint` and `make test` pass.
- Tests exist for: list filters, search and saved views; CSV export needs the right and is logged; exactly one main contact; adding a contact offers an existing person; unlinking keeps the person; encrypted fields are masked and "Show" is logged; panels hidden by client type; file type and size rules; a document address without signing in redirects; a sensitive download writes an event; soft delete hides and owner purge removes; status rules; archive needs a reason; delete needs the right; every new address refuses signed-out users.
- Screenshots in `docs/screens/stage-02/`: client list, a company's Info tab, Contacts tab, Documents tab, search drop-down.

## Not in this stage

Companies House lookups (Stage 3). Services and fees (Stage 4). Tasks (Stage 5). The portal share switch on documents can exist as a field but has no effect until Stage 10.
