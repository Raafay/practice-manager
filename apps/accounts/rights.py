"""The rights a role or a single user can hold. See docs/specs/01-security-and-users.md section 2.

Seeing and editing clients, contacts, tasks, deadlines and requests needs no
right: every active staff member can do it.
"""

RIGHTS: dict[str, str] = {
    "fees.view": "See client fees",
    "finance.owner": "Finance pages: forecast, targets, Xero totals, hourly rates",
    "aml.approve": "Approve AML risk assessments",
    "documents.sensitive": "View identity documents (each view is logged)",
    "comms.approve": "Approve and send queued messages",
    "comms.approve_fees": "Approve fee-chasing messages",
    "comms.pause": "Pause messages to a client",
    "settings.manage": "Change settings: services, templates, statuses, stages",
    "users.manage": "Add users, change roles and teams",
    "data.export": "Export lists to CSV",
    "data.import": "Run imports",
    "clients.status": "Change a client's status",
    "clients.archive": "Archive a client",
    "clients.delete": "Delete a client for good",
    "onboarding.override": "Make a client live without full onboarding",
    "integrations.manage": "Connect Xero and other services",
    "time.edit_all": "Edit anyone's time entries",
    "audit.view": "View the audit log",
    "system.view": "View system status and background jobs",
    "retention.manage": "Review retention dates and remove data for good",
}

MANAGER_DEFAULTS = [
    "fees.view",
    "documents.sensitive",
    "comms.approve",
    "comms.approve_fees",
    "comms.pause",
    "settings.manage",
    "data.export",
    "clients.status",
    "clients.archive",
    "time.edit_all",
]

STAFF_DEFAULTS = ["fees.view", "documents.sensitive", "comms.approve"]


class UnknownRight(ValueError):
    """Raised for a right name that is not in RIGHTS, so a typo never passes silently."""


def check_right(name: str) -> str:
    if name not in RIGHTS:
        raise UnknownRight(name)
    return name
