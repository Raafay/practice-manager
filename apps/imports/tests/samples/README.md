# Sample import files

Made up for tests. No real people, companies or tax references.

- `clients_clean.csv`: headings in the style a practice system exports; four good rows.
- `clients_messy.csv`: byte order mark, semicolons, spaces, a short company number, both date
  formats, a duplicate name, an unknown type, a bad date with a formula in another cell, a blank line.
- `contacts.csv`: people for the clean clients, plus an unknown client and an unknown role.
- `services.csv`: services and fees for the clean clients, plus one that does not apply and one
  that does not exist.

Company numbers match the Companies House samples in `apps/companieshouse/tests/samples/`.
