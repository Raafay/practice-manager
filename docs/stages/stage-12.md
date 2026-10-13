# Stage 12: Import and reports

Goal: the owner can bring clients, contacts, services and fees across from a BrightManager export without typing them in, and can pull the reports the practice needs.

Read first: `docs/specs/11-import-and-reports.md`.

Use made-up CSV files only. Write them under `apps/imports/tests/samples/`: a clean clients file with headings in the style a practice system would export, a messy one (duplicates, bad dates, unknown types, a byte order mark, a semicolon delimiter), a contacts file and a services file.

## Build

1. `apps/imports`: `ImportRun`, the tagging of created records, and the four-step wizard in section 2. Settings, Import, for users with `data.import`.

2. Column matching with suggestions from header text, and saved matchings.

3. The check step with row-by-row problems, and the import step in one transaction with a downloadable file of failures.

4. Matching to existing records and the cleaning rules.

5. Undo for a run.

6. "Fetch from Companies House" for imported clients, running in the background through the jobs app with progress on the page.

7. The migration helper for clearing deadlines already dealt with.

8. Reports, section 3: build those marked Stage 12, and bring the earlier ones (Deadlines, Client list, AML register) under one Reports page with a common filter and export pattern.

9. The client summary PDF and the "Generate report" button on the client page.

10. Make every CSV export safe against spreadsheet formulas, in one shared helper, and move the earlier exports onto it.

## Checks

- `make lint` and `make test` pass.
- Every test in section 4 of the spec exists.
- Also: an import by a manager is refused; an import of 500 rows finishes in reasonable time and uses bulk writes; a failed row does not stop good rows; the migration helper marks only what was ticked; each report's filters; the summary PDF hides fees without the right.
- Screenshots in `docs/screens/stage-12/`: the column matching step, the check step with problems, the Reports page, a client summary PDF rendered to an image.
- In the pull request, give the user the list of fields the import accepts, so they know what to ask for in the BrightManager export.

## Not in this stage

Importing history: past tasks, emails, time and documents. Only current clients, contacts, services and fees come across.
