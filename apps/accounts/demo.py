"""Made-up staff and teams for development. Every name here is invented."""

from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret

from apps import events

from .models import Role, Team, User

DEMO_PASSWORD = "demo-password-2026"

PEOPLE = [
    # email, name, role, job title, colour, teams
    (
        "morgan.hale@example.com",
        "Morgan Hale",
        Role.OWNER,
        "Practice owner",
        "#7c3aed",
        ["Advisory"],
    ),
    (
        "priya.castell@example.com",
        "Priya Castell",
        Role.MANAGER,
        "Practice manager",
        "#0f766e",
        ["Compliance", "Advisory"],
    ),
    (
        "sam.whitlow@example.com",
        "Sam Whitlow",
        Role.STAFF,
        "Accounts senior",
        "#b45309",
        ["Compliance"],
    ),
    (
        "jordan.pike@example.com",
        "Jordan Pike",
        Role.STAFF,
        "Payroll and VAT",
        "#be123c",
        ["Compliance"],
    ),
    (
        "ellis.marr@example.com",
        "Ellis Marr",
        Role.STAFF,
        "Advisory associate",
        "#1d4ed8",
        ["Advisory"],
    ),
]

TEAMS = {
    "Compliance": "Accounts, tax, VAT and payroll deadlines.",
    "Advisory": "Fractional finance director work.",
}


def ensure_totp(user: User) -> None:
    if not Authenticator.objects.filter(user=user, type=Authenticator.Type.TOTP).exists():
        TOTP.activate(user, generate_totp_secret())


def seed() -> list[tuple[str, str, str]]:
    """Create or refresh the demo staff. Returns (name, email, role) for each person."""
    roles = {role.slug: role for role in Role.objects.all()}
    teams = {}
    for name, description in TEAMS.items():
        teams[name], _ = Team.objects.update_or_create(
            name=name, defaults={"description": description}
        )

    created = []
    for email, name, role_slug, job_title, colour, team_names in PEOPLE:
        user = User.objects.filter(email=email).first()
        is_new = user is None
        if is_new:
            user = User(email=email)
        user.name = name
        user.kind = User.Kind.STAFF
        user.role = roles[role_slug]
        user.job_title = job_title
        user.colour = colour
        user.is_active = True
        user.deactivated_at = None
        user.set_password(DEMO_PASSWORD)
        user.save()
        user.teams.set([teams[team] for team in team_names])
        ensure_totp(user)
        if is_new:
            events.record(None, "user.created", f"Demo user {user} was created.", target=user)
            events.notify(user, "Welcome. This is demo data, made up for trying the app.", "/")
        created.append((name, email, roles[role_slug].name))
    return created
