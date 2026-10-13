# Practice Manager (working title)

A private web app for one accountancy practice, built to replace BrightManager. This file is for the person running the build. Claude Code reads `CLAUDE.md` instead.

The app is built in thirteen stages. Each stage is one Claude Code session that ends in one pull request. The plan is in `docs/PLAN.md`.

## What is in this repository

- `CLAUDE.md`: the standing instructions Claude Code reads at the start of every session.
- `docs/PLAN.md`: the list of stages and the prompt to paste.
- `docs/stages/`: one brief per stage.
- `docs/specs/`: the detail for each part of the product. A stage reads only the ones it needs.
- `docs/DECISIONS.md`: what has been decided, and the defaults to confirm with the practice owner.
- `docs/STATUS.md`: where the build has got to. Claude Code keeps it up to date.
- `docs/reference/`: notes on how BrightManager looks in use.
- `scripts/`: a script that prepares a cloud session, and one that takes screenshots.

## Running a stage

1. Open Claude Code and start a cloud session on this repository, on the main branch.
2. Leave the model on Sonnet. It is the cheaper one and it is good enough for building.
3. Choose Plan mode, and paste the prompt from `docs/PLAN.md` with the stage number filled in.
4. Read the plan it comes back with. It should match the stage brief. Approve it.
5. Leave it to work. A stage can take an hour or more. You can close the window and come back.
6. When it finishes, open the pull request. Read the summary, look at the screenshots under `docs/screens/`, and follow the "How to check" steps.
7. If it looks right, merge the pull request. Then start the next stage in a new session.

Things that keep the cost down:

- One stage per session. A long session resends its whole history with every step, so a fresh session for each stage is much cheaper.
- Do not chat in a build session. If you want to ask something general, ask it somewhere else.
- If a stage goes wrong, do not argue with it for long. Stop it, start a new session, and use the "Continue" or "Fix" prompt from `docs/PLAN.md` with a clear description of the problem.

## Looking at the app on your Mac

The easy way: in the Claude desktop app, open this folder as a local session and ask it to pull the latest main branch, set the app up, load the demo data and open it in the preview.

By hand, once Stage 1 is merged:

    git pull
    make setup
    make seed
    make dev

Then open `http://localhost:8000`. `make seed` prints the sign-in details for the made-up staff. The first time, you need uv installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`). For a quick look you do not need PostgreSQL: copy `.env.example` to `.env` and set `DATABASE_URL=sqlite:///local.sqlite3`.

## Accounts with other services, and when each is needed

| Service | What it is for | Needed by | Who sets it up |
|---|---|---|---|
| GitHub | Holds the code. Cloud sessions work from it. | Now | You |
| Companies House developer account | A free key that lets the app read company details and filing dates. | To check Stage 3 against real data | You, in about five minutes |
| A hosting company | Runs the site, its database and its file storage. A monthly bill. | Stage 13 | You |
| The practice's domain | So the site lives at an address such as `app.` followed by the practice's domain, and so emails can be proved to come from the practice. | Stage 13 | Whoever controls the domain's DNS settings |
| An email-sending service | Sends reminders and sign-in codes reliably. | Stage 13 | You |
| Xero developer app | Lets the app read invoices and payments. The practice owner clicks "Connect" once. | After Stage 13, to use Stage 11 for real | You create the app, the owner connects |
| Later, if wanted | A text message provider, a paid identity-check service, HMRC developer access. | After the first version | |

Cloud sessions cannot reach Companies House or Xero, so those parts are built and tested against sample data. To let a cloud session make one live Companies House check, edit the cloud environment: set network access to Custom, add `api.company-information.service.gov.uk`, keep the default list ticked, and add `COMPANIES_HOUSE_API_KEY=your key` to the environment variables. Or run the check on your Mac instead.

## Rules for the person running the build

- No real client data goes in until every line of the go-live checklist from Stage 13 is ticked. Until then the app holds made-up data only.
- Never paste real client names, emails, tax references or documents into a Claude Code session or into this repository.
- The practice owner reads and agrees the deadline rules (`docs/specs/03-services-and-deadlines.md`) and the AML risk questions (`docs/specs/06-onboarding-and-aml.md`) before go-live. The practice stays responsible for both.
- Keep BrightManager running alongside for at least one full month after go-live.
