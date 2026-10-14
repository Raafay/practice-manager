"""The URL walk (spec 12, sections 1 and 7).

Every address in the project is visited by six kinds of user, with real records from
the demo data, and the answer is checked against the table below. An address with no
line in the table fails the test, so a new view cannot be added without deciding who
may reach it.

Kinds of user: signed out, portal, staff, manager, owner, and "limited" (a staff
member whose role holds no rights at all, so every right check is exercised).

Rules in the table:

    staff         any active staff member with two-factor
    <right>       staff holding that right (see ROLE_RIGHTS, copied from spec 01 section 2)
    portal        a signed-in portal user; staff get 403
    public        anyone; signed-out visitors are not sent to sign in
    open          anyone; no check beyond "no server error" (signing out, the code step)
    refused       staff rule, but everyone is refused: the Xero callback without a
                  matching sign-in state from Xero
    signin        allauth's sign-in pages: open when signed out, closed to portal users
    account       allauth's pages for a signed-in staff member's own account
    get=X post=Y  a different rule for each method

Rights checked deeper than the view (approving a message, sending back an
assessment) cannot be reached by an empty POST; those lines say "staff" and the
app's own tests cover the right. Time entries and the sent-back assessment are
someone else's, so the walk sees the time.edit_all check.

Each request runs in a savepoint that is rolled back, so one visit cannot change the
next. The Django admin (/control/) is checked separately: owner only.
"""

import re
import uuid
from http.cookies import SimpleCookie

import pytest
from django.contrib import admin
from django.core.cache import cache
from django.core.management import call_command
from django.db import transaction
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.accounts.models import Role
from apps.accounts.rights import RIGHTS
from apps.accounts.tests.factories import (
    UserFactory,
    manager,
    owner,
    portal_user,
    sign_in,
    staff,
)

pytestmark = pytest.mark.django_db

# Spec 01 section 2, with CORRECTIONS 16. Written out here, not read from the code,
# so a change to the seeded roles shows up as a failure.
ROLE_RIGHTS = {
    "owner": set(RIGHTS),
    "manager": {
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
    },
    "staff": {"fees.view", "documents.sensitive", "comms.approve"},
    "limited": set(),
}
STAFF_KINDS = ("staff", "manager", "owner", "limited")
SIGN_IN_PAGES = ("/login/", "/portal/login/", "/2fa/totp/activate/", "/control/login/")

EXPECTED_TABLE = """
overview                            staff

# allauth: signing in, and a staff member's own account
account_login                       signin
account_logout                      open
account_inactive                    signin
account_signup                      signin
account_reauthenticate              account
account_email                       public
account_email_verification_sent     signin
account_change_password             account
account_set_password                account
account_reset_password              signin
account_confirm_login_code          signin
account_confirm_email               signin
account_reset_password_from_key_done signin
account_reset_password_from_key     signin
account_reset_password_done         signin
mfa_index                           account
mfa_authenticate                    signin
mfa_reauthenticate                  account
mfa_trust                           account
mfa_activate_totp                   account
mfa_deactivate_totp                 account
mfa_view_recovery_codes             account
mfa_generate_recovery_codes         account
mfa_download_recovery_codes         account

core:healthz                        public
core:styleguide                     staff
core:styleguide_demo                staff
core:settings                       staff
core:practice_settings              settings.manage
core:practice_logo                  staff
core:security_settings              users.manage
core:system                         system.view
core:system_backup                  system.view

accounts:profile                    staff
accounts:accept_invitation          public
accounts:users                      users.manage
accounts:invite                     users.manage
accounts:cancel_invitation          users.manage
accounts:user_detail                users.manage
accounts:user_role                  users.manage
accounts:user_rights                users.manage
accounts:user_teams                 users.manage
accounts:user_reset_mfa             users.manage
accounts:user_deactivate            users.manage
accounts:user_reactivate            users.manage
accounts:teams                      users.manage
accounts:team_create                users.manage
accounts:team_edit                  users.manage
accounts:team_delete                users.manage
accounts:roles                      users.manage

events:audit_log                    audit.view
events:notifications                staff
events:notifications_read_all       staff
events:notification_open            staff

clients:list                        staff
clients:new                         staff
clients:export                      data.export
clients:view_save                   staff
clients:view_delete                 staff
clients:search_dropdown             staff
clients:search                      staff
clients:detail                      staff
clients:timeline                    staff
clients:contacts                    staff
clients:links                       staff
clients:documents                   staff
clients:panel                       staff
clients:panel_edit                  staff
clients:client_reveal               staff
clients:status                      clients.status
clients:archive                     clients.archive
clients:restore                     clients.archive
clients:delete                      clients.delete
clients:add_note                    staff
clients:log_call                    staff
clients:pin_note                    staff
clients:contact_add                 staff
clients:contact_link                staff
clients:contact_edit                staff
clients:contact_unlink              staff
clients:link_add                    staff
clients:link_remove                 staff
clients:contact_detail              staff
clients:contact_detail_edit         staff
clients:contact_reveal              staff
clients:contact_export              retention.manage
clients:contact_purge               retention.manage
clients:retention                   retention.manage
clients:personal_tax_client         staff
clients:document_upload             staff
clients:document_download           get=documents.sensitive post=staff
clients:document_preview            get=documents.sensitive post=staff
clients:document_edit               staff
clients:document_delete             staff
clients:document_purge              retention.manage
clients:tags                        settings.manage
clients:tag_add                     settings.manage
clients:tag_edit                    settings.manage
clients:tag_delete                  settings.manage
clients:custom_fields               settings.manage
clients:custom_field_add            settings.manage
clients:custom_field_edit           settings.manage
clients:custom_field_delete         settings.manage

jobs:list                           system.view
jobs:run_now                        system.view

companieshouse:add                  staff
companieshouse:preview              staff
companieshouse:tab                  staff
companieshouse:sync                 staff
companieshouse:fill_in              staff
companieshouse:integrations         integrations.manage

services:list                       settings.manage
services:add                        settings.manage
services:edit                       settings.manage
services:move                       settings.manage
services:toggle                     settings.manage
services:panel                      staff
services:switch_on                  staff
services:settings                   staff
services:switch_off                 staff
services:fee                        get=staff post=fees.view
services:client_deadlines           staff
services:deadline_done              staff
services:deadline_not_required      staff
services:deadline_reopen            staff
services:deadline_date              staff
services:report_deadlines           staff
services:report_deadlines_export    data.export

tasks:list                          staff
tasks:new                           staff
tasks:client_options                staff
tasks:bulk                          staff
tasks:board_move                    staff
tasks:calendar_move                 staff
tasks:view_save                     staff
tasks:view_default                  staff
tasks:view_delete                   staff
tasks:projects                      staff
tasks:project_new                   staff
tasks:project                       staff
tasks:project_edit                  staff
tasks:project_section_add           staff
tasks:repeating                     staff
tasks:repeating_new                 staff
tasks:repeating_edit                staff
tasks:repeating_toggle              staff
tasks:workload                      staff
tasks:detail                        staff
tasks:field                         staff
tasks:complete                      staff
tasks:cancel                        staff
tasks:star                          staff
tasks:follow                        staff
tasks:step_pick                     staff
tasks:step                          staff
tasks:comment                       staff
tasks:description                   staff
tasks:attach                        staff
tasks:client_tasks                  staff
tasks:statuses                      settings.manage
tasks:status_add                    settings.manage
tasks:status_edit                   settings.manage
tasks:status_delete                 settings.manage
tasks:status_move                   settings.manage
tasks:status_merge                  settings.manage
tasks:categories                    settings.manage
tasks:category_add                  settings.manage
tasks:category_edit                 settings.manage
tasks:category_delete               settings.manage
tasks:category_move                 settings.manage
tasks:category_merge                settings.manage
tasks:service_templates             settings.manage
tasks:template_add                  settings.manage
tasks:template_edit                 settings.manage

comms:queue                         staff
comms:bulk_approve                  staff
comms:pause                         get=staff post=comms.pause
comms:bulk_email                    staff
comms:message                       staff
comms:compose                       staff
comms:log_email                     staff
comms:letter                        staff
comms:sms                           staff
comms:webhook                       open
comms:templates                     settings.manage
comms:template_add                  settings.manage
comms:template_edit                 settings.manage
comms:template_delete               settings.manage
comms:template_toggle               settings.manage
comms:reminders                     settings.manage
comms:reminder_edit                 settings.manage
comms:reminder_toggle               settings.manage

onboarding:tab                      staff
onboarding:item                     staff
onboarding:make_live                clients.status
onboarding:checklist                settings.manage
onboarding:checklist_add            settings.manage
onboarding:checklist_edit           settings.manage
onboarding:checklist_delete         settings.manage
onboarding:engagement               staff
onboarding:prepare                  fees.view
onboarding:letter                   fees.view
onboarding:letter_cancel            fees.view
onboarding:letter_cancel_link       fees.view
onboarding:letter_parts             settings.manage
onboarding:letter_part              settings.manage
onboarding:sign                     public
onboarding:sign_pdf                 public
onboarding:hmrc                     staff
onboarding:hmrc_add                 staff
onboarding:hmrc_edit                staff
onboarding:hmrc_reveal              staff
onboarding:clearance_start          staff
onboarding:clearance_update         staff
onboarding:clearance_chase          staff

aml:tab                             staff
aml:identity                        staff
aml:person_add                      staff
aml:person_remove                   staff
aml:start                           staff
aml:assessment                      staff
aml:approve                         get=staff post=aml.approve
aml:send_back                       get=aml.approve post=staff
aml:questions                       settings.manage
aml:question_add                    settings.manage
aml:question_edit                   settings.manage
aml:question_toggle                 settings.manage
aml:bands                           settings.manage
aml:records                         settings.manage
aml:training_add                    settings.manage
aml:training_delete                 settings.manage
aml:policy_add                      settings.manage
aml:policy                          staff
aml:policy_delete                   settings.manage
aml:register                        staff
aml:register_export                 data.export

pipeline:prospects                  staff
pipeline:prospect_new               staff
pipeline:move                       staff
pipeline:sales_edit                 staff
pipeline:meeting_add                staff
pipeline:proposal_new               fees.view
pipeline:proposal                   fees.view
pipeline:proposal_send              fees.view
pipeline:proposal_withdraw          fees.view
pipeline:proposal_cancel_link       fees.view
pipeline:stages                     settings.manage
pipeline:stage_add                  settings.manage
pipeline:stage_edit                 settings.manage
pipeline:stage_delete               settings.manage
pipeline:rules                      settings.manage
pipeline:proposal_page              public
pipeline:proposal_pdf               public

portal:login                        public
portal:login_code                   open
portal:logout                       open
portal:home                         portal
portal:switch                       portal
portal:documents                    portal
portal:upload                       portal
portal:document                     portal
portal:requests                     portal
portal:request_new                  portal
portal:request_detail               portal
portal:details                      portal
portal:item                         portal
portal:item_upload                  portal
portal:item_everything              portal
portal:item_approve                 portal
portal:form                         portal
portal:request_form                 public
portal:request_thanks               public
portal:inbox                        staff
portal:inbox_log                    staff
portal:inbox_detail                 staff
portal:inbox_convert                staff
portal:inbox_link                   staff
portal:inbox_reply                  staff
portal:inbox_close                  staff
portal:inbox_spam                   staff
portal:inbox_reopen                 staff
portal:inbox_client                 staff
portal:inbox_file                   staff
portal:client_requests              staff
portal:replace_link                 staff
portal:invite                       staff
portal:withdraw                     staff
portal:item_cancel                  staff
portal:task_ask_upload              staff
portal:task_ask_approve             staff
portal:review                       staff
portal:review_act                   staff

timekeeping:sheet                   staff
timekeeping:cell                    staff
timekeeping:log                     staff
timekeeping:edit                    time.edit_all
timekeeping:delete                  get=staff post=time.edit_all
timekeeping:timer_start             staff
timekeeping:timer_stop              staff
timekeeping:client_log              staff
timekeeping:client_tab              staff

finance:fees                        finance.owner
finance:invoices                    finance.owner
finance:chase                       finance.owner
finance:targets                     finance.owner
finance:forecast                    finance.owner
finance:summary                     finance.owner
finance:settings                    finance.owner
finance:matching                    finance.owner
finance:match_confirm               finance.owner
finance:match_unmatch               finance.owner
finance:match_ignore                finance.owner
finance:xero_connect                integrations.manage
finance:xero_callback               get=refused post=finance.owner
finance:xero_disconnect             finance.owner
finance:xero_sync                   finance.owner
finance:client_fees                 get=fees.view post=staff
finance:send_to_xero                finance.owner

imports:index                       data.import
imports:match                       data.import
imports:check                       data.import
imports:run                         data.import
imports:failures                    data.import
imports:undo                        data.import
imports:fetch                       data.import
imports:progress                    data.import
imports:matching_delete             data.import
imports:helper                      data.import

reports:index                       staff
reports:client_summary              staff
reports:tasks                       staff
reports:tasks_export                data.export
reports:services                    staff
reports:services_export             data.export
reports:time                        staff
reports:time_export                 data.export
reports:requests                    staff
reports:requests_export             data.export
reports:pipeline                    staff
reports:pipeline_export             data.export
reports:communications              staff
reports:communications_export       data.export
"""


def parse_table(text):
    table = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, *rules = line.split()
        if len(rules) == 1:
            table[name] = {"get": rules[0], "post": rules[0]}
        else:
            table[name] = dict(rule.split("=", 1) for rule in rules)
    return table


EXPECTED = parse_table(EXPECTED_TABLE)


def all_patterns():
    """(name, route) for every named address except the Django admin's."""
    found = {}

    def walk(patterns, namespace, prefix):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                if entry.namespace == "admin":
                    continue
                walk(entry.url_patterns, entry.namespace or namespace, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern) and entry.name:
                name = f"{namespace}:{entry.name}" if namespace else entry.name
                found.setdefault(name, prefix + str(entry.pattern))

    walk(get_resolver().url_patterns, None, "")
    return found


# ---------------------------------------------------------------------------
# Filling in the address: real records from the demo data where there is one.

DUMMY_ID = 999999


class World:
    """Picks one record of each kind from the demo data."""

    def __init__(self):
        from apps.accounts.models import Invitation, Team, User
        from apps.aml.models import (
            IdentityCheck,
            PolicyDocument,
            RiskAssessment,
            RiskQuestion,
            TrainingRecord,
        )
        from apps.clients.models import (
            Client as ClientRecord,
        )
        from apps.clients.models import (
            ClientContact,
            ClientLink,
            Contact,
            CustomFieldDefinition,
            Document,
            Note,
            SavedView,
            Tag,
        )
        from apps.comms.models import MessageTemplate, QueuedMessage, ReminderSchedule
        from apps.events.models import Notification
        from apps.finance.models import XeroContact
        from apps.imports.models import ImportRun, SavedMatching
        from apps.jobs import registry
        from apps.onboarding.models import (
            AgentAuthorisation,
            ChecklistTemplateItem,
            ClearanceRequest,
            EngagementLetter,
            LetterPart,
            OnboardingItem,
        )
        from apps.pipeline.models import PipelineStage, Proposal
        from apps.portal.models import PortalForm, PortalItem, Request, RequestFile
        from apps.services.models import ClientService, Deadline, Service
        from apps.tasks.models import (
            Project,
            RepeatingTask,
            Task,
            TaskCategory,
            TaskStatus,
            TaskStep,
            TaskTemplate,
        )
        from apps.timekeeping.models import TimeEntry

        active = ClientRecord.objects.filter(client_services__isnull=False, status="active")
        self.client = active.order_by("pk").first()
        self.models = {
            "Contact": Contact,
            "Task": Task.objects.filter(client__isnull=False),
            "SavedView": SavedView,
            "Project": Project,
            "RepeatingTask": RepeatingTask,
            "User": User.objects.filter(kind=User.Kind.STAFF),
            "Invitation": Invitation,
            "Team": Team,
            "Tag": Tag,
            "CustomFieldDefinition": CustomFieldDefinition,
            "Service": Service,
            "TaskStatus": TaskStatus,
            "TaskCategory": TaskCategory,
            "TaskTemplate": TaskTemplate,
            "MessageTemplate": MessageTemplate,
            "ReminderSchedule": ReminderSchedule,
            "ChecklistTemplateItem": ChecklistTemplateItem,
            "RiskQuestion": RiskQuestion,
            "TrainingRecord": TrainingRecord,
            "PolicyDocument": PolicyDocument,
            "PipelineStage": PipelineStage,
            "Prospect": ClientRecord.objects.filter(status="prospect"),
            "QueuedMessage": QueuedMessage.objects.filter(client__isnull=False),
            "Notification": Notification,
            "Request": Request.objects.filter(client__isnull=False),
            "PortalForm": PortalForm,
            "TimeEntry": TimeEntry,
            "XeroContact": XeroContact,
            "ImportRun": ImportRun,
            "SavedMatching": SavedMatching,
            # Records that belong to a client: the client is taken from the record.
            "Note": Note,
            "ClientContact": ClientContact,
            "ClientLink": ClientLink,
            "ClientService": ClientService,
            "Deadline": Deadline,
            "OnboardingItem": OnboardingItem,
            "EngagementLetter": EngagementLetter,
            "AgentAuthorisation": AgentAuthorisation,
            "ClearanceRequest": ClearanceRequest,
            "IdentityCheck": IdentityCheck,
            "RiskAssessment": RiskAssessment.objects.filter(state="submitted"),
            "DraftAssessment": RiskAssessment.objects.filter(state="draft"),
            "Proposal": Proposal,
            "PortalItem": PortalItem,
            "SensitiveDocument": Document.objects.filter(sensitive=True, deleted_at__isnull=True),
            "Document": Document.objects.filter(deleted_at__isnull=True),
            "RequestFile": RequestFile,
            "TaskStep": TaskStep,
        }
        self.letter_part_key = getattr(LetterPart.objects.first(), "key", "x")
        self.job_name = registry.all_jobs()[0].name

    def first(self, key):
        source = self.models[key]
        queryset = source.objects.all() if isinstance(source, type) else source
        return queryset.order_by("pk").first()


# By route prefix: which record "pk" means. The first match wins.
PK_BY_PREFIX = [
    ("clients/views/", "SavedView"),
    ("clients/", "Client"),
    ("contacts/", "Contact"),
    ("tasks/views/", "SavedView"),
    ("tasks/projects/", "Project"),
    ("tasks/repeating/", "RepeatingTask"),
    ("tasks/", "Task"),
    ("settings/users/invitations/", "Invitation"),
    ("settings/users/", "User"),
    ("settings/teams/", "Team"),
    ("settings/tags/", "Tag"),
    ("settings/custom-fields/", "CustomFieldDefinition"),
    ("settings/services/", "Service"),
    ("settings/task-statuses/", "TaskStatus"),
    ("settings/task-categories/", "TaskCategory"),
    ("settings/templates/", "MessageTemplate"),
    ("settings/reminders/", "ReminderSchedule"),
    ("settings/onboarding-checklist/", "ChecklistTemplateItem"),
    ("settings/risk-questions/", "RiskQuestion"),
    ("settings/aml-records/training/", "TrainingRecord"),
    ("settings/aml-records/policy/", "PolicyDocument"),
    ("settings/pipeline-stages/", "PipelineStage"),
    ("settings/import/matchings/", "SavedMatching"),
    ("settings/import/", "ImportRun"),
    ("prospects/", "Prospect"),
    ("messages/", "QueuedMessage"),
    ("notifications/", "Notification"),
    ("requests/", "Request"),
    ("portal-forms/", "PortalForm"),
    ("time/entries/", "TimeEntry"),
    ("finance/xero/contacts/", "XeroContact"),
]

# Second arguments, and the record they name. The client in the address is the
# record's own client.
SUB_RECORDS = {
    "note_pk": "Note",
    "link_pk": "ClientContact",
    "cs_pk": "ClientService",
    "deadline_pk": "Deadline",
    "letter_pk": "EngagementLetter",
    "auth_pk": "AgentAuthorisation",
    "req_pk": "ClearanceRequest",
    "check_pk": "IdentityCheck",
    "assessment_pk": "RiskAssessment",
    "proposal_pk": "Proposal",
    "step_pk": "TaskStep",
    "template_pk": "TaskTemplate",
}
BY_NAME = {
    "clients:link_remove": {"link_pk": "ClientLink"},
    "onboarding:item": {"item_pk": "OnboardingItem"},
    "portal:item_cancel": {"item_pk": "PortalItem"},
    "clients:document_download": {"public_id": "SensitiveDocument"},
    "clients:document_preview": {"public_id": "SensitiveDocument"},
    "clients:document_edit": {"public_id": "Document"},
    "clients:document_delete": {"public_id": "Document"},
    "clients:document_purge": {"public_id": "Document"},
    "aml:assessment": {"assessment_pk": "DraftAssessment"},
    "portal:inbox_file": {"public_id": "RequestFile"},
}
STRINGS = {
    "kind": "drawer",
    "direction": "up",
    "number": "00000000",
    "uidb36": "zz",
    "key": "x",
    "token": "not-a-real-token",
    "public_id": uuid.UUID(int=1),
}


def client_of(record):
    for attr in ("client", "client_a"):
        if hasattr(record, attr):
            return getattr(record, attr)
    for parent in ("task", "request", "client_service"):
        if hasattr(record, parent):
            return client_of(getattr(record, parent))
    return None


def fill_kwargs(world, name, route):
    names = re.findall(r"<(?:\w+:)?(\w+)>", route)
    if not names:
        return {}
    kwargs = {}
    client = None
    overrides = BY_NAME.get(name, {})
    for arg in names:
        key = overrides.get(arg) or SUB_RECORDS.get(arg)
        if key:
            record = world.first(key)
            if record is None:
                kwargs[arg] = STRINGS["public_id"] if arg == "public_id" else DUMMY_ID
                continue
            if route.startswith("requests/") and hasattr(record, "request"):
                kwargs["pk"] = record.request_id
            kwargs[arg] = getattr(record, "public_id", None) if arg == "public_id" else record.pk
            client = client or client_of(record)
        elif arg in ("client_pk",):
            kwargs[arg] = world.client.pk
    for arg in names:
        if arg in kwargs:
            continue
        if arg == "pk":
            if route.startswith("clients/<int:pk>") or route.startswith("clients/<int:client_pk>"):
                kwargs[arg] = (client or world.client).pk
                continue
            key = next((k for prefix, k in PK_BY_PREFIX if route.startswith(prefix)), None)
            record = world.client if key == "Client" else (world.first(key) if key else None)
            kwargs[arg] = record.pk if record is not None else DUMMY_ID
        elif arg == "client_pk":
            kwargs[arg] = world.client.pk
        elif arg == "contact_pk":
            kwargs[arg] = world.first("Contact").pk
        elif arg == "service_pk":
            kwargs[arg] = world.first("Service").pk
        elif arg == "field":
            kwargs[arg] = {"clients:client_reveal": "company_utr", "tasks:field": "title"}.get(
                name, "ni_number"
            )
        elif arg == "key" and name == "onboarding:letter_part":
            kwargs[arg] = world.letter_part_key
        elif arg == "key" and name.startswith("clients:panel"):
            kwargs[arg] = "company"
        elif arg == "name":
            kwargs[arg] = world.job_name
        elif arg == "token" and name == "portal:request_form":
            kwargs[arg] = world.client.request_token or "not-a-real-token"
        elif arg == "public_id":
            record = world.first("Document")
            kwargs[arg] = record.public_id if record else STRINGS["public_id"]
        else:
            kwargs[arg] = STRINGS.get(arg, DUMMY_ID)
    return kwargs


# ---------------------------------------------------------------------------
# What each kind of user should get.


def is_sign_in_redirect(response):
    return response.status_code in (301, 302) and response["Location"].split("?")[0].startswith(
        SIGN_IN_PAGES
    )


def allowed(response):
    """Not refused: anything but 403, a 500, or being sent to a sign-in page."""
    return response.status_code not in (401, 403, 500) and not is_sign_in_redirect(response)


def check(kind, rule, response):
    """Return None if the response matches the rule, else a short reason."""
    status = response.status_code
    if status >= 500:
        return f"server error {status}"
    if rule == "open":
        return None
    if rule == "refused":
        if kind == "anon":
            return None if is_sign_in_redirect(response) else f"signed out got {status}"
        return None if status == 403 else f"got {status}, expected 403"
    if rule == "public":
        if kind == "anon" and (status == 403 or is_sign_in_redirect(response)):
            return "public page refused a signed-out visitor"
        return None
    if rule == "signin":
        if kind == "portal":
            return None if status == 403 else f"portal user got {status}, expected 403"
        if kind == "anon" and status == 403:
            return "sign-in page refused a signed-out visitor"
        return None
    if rule == "portal":
        if kind == "anon":
            location = response.get("Location", "")
            return None if location.startswith("/portal/login/") else f"anon got {status}"
        if kind == "portal":
            return None if allowed(response) else f"portal user refused ({status})"
        return None if status == 403 else f"staff on a portal page got {status}, expected 403"
    # staff, account and right rules
    if kind == "anon":
        location = response.get("Location", "")
        return None if location.startswith("/login/") else f"signed out got {status}"
    if kind == "portal":
        return None if status == 403 else f"portal user got {status}, expected 403"
    if rule in ("staff", "account"):
        return None if allowed(response) else f"refused ({status})"
    if rule not in RIGHTS:
        return f"unknown rule {rule!r}"
    if rule in ROLE_RIGHTS[kind]:
        return None if allowed(response) else f"holds {rule} but was refused ({status})"
    return None if status == 403 else f"lacks {rule} but got {status}, expected 403"


# ---------------------------------------------------------------------------


def test_every_address_has_an_entry():
    found = set(all_patterns())
    missing = sorted(found - set(EXPECTED))
    stale = sorted(set(EXPECTED) - found)
    assert not missing, f"Add these addresses to EXPECTED_TABLE: {missing}"
    assert not stale, f"These lines name addresses that no longer exist: {stale}"


def test_the_role_table_matches_the_seeded_roles():
    for slug in ("manager", "staff"):
        assert set(Role.objects.get(slug=slug).rights) == ROLE_RIGHTS[slug], slug


def make_users():
    limited_role = Role.objects.create(slug="limited", name="Limited", order=9, rights=[])
    users = {
        "anon": None,
        "portal": portal_user(),
        "staff": staff(),
        "manager": manager(),
        "owner": owner(),
        "limited": UserFactory(role=limited_role),
    }
    clients = {}
    for kind, user in users.items():
        client = Client(raise_request_exception=False)
        if user is not None:
            sign_in(client, user)
        clients[kind] = client
    return clients


def visit(http, method, url):
    """One request, undone afterwards. Cookies are put back too: signing out
    replaces the session cookie with one whose session was rolled back."""
    cache.clear()
    cookies = SimpleCookie(http.cookies)
    with transaction.atomic():
        response = getattr(http, method)(url)
        transaction.set_rollback(True)
    http.cookies = cookies
    return response


def test_the_url_walk(settings):
    call_command("seed_demo", verbosity=0)
    world = World()
    clients = make_users()
    failures, made_up = [], []
    for name, route in sorted(all_patterns().items()):
        rules = EXPECTED.get(name)
        if rules is None:
            continue  # reported by test_every_address_has_an_entry
        kwargs = fill_kwargs(world, name, route)
        if DUMMY_ID in kwargs.values() or STRINGS["public_id"] in kwargs.values():
            made_up.append(name)
        url = reverse(name, kwargs=kwargs or None)
        for kind, http in clients.items():
            for method in ("get", "post"):
                response = visit(http, method, url)
                problem = check(kind, rules[method], response)
                if problem:
                    failures.append(f"{name} {method.upper()} {url} as {kind}: {problem}")
    assert not failures, "\n".join(failures)
    # Nearly every address is visited with a real record, so object-level checks run.
    # The demo data has no invitation, AML policy or training record, saved client view,
    # clearance request or request file; those few use made-up ids.
    assert len(made_up) <= 12, made_up


def test_the_control_pages_are_for_the_owner_only():
    clients = make_users()
    urls = [reverse("admin:index")] + [
        reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
        for model in admin.site._registry
    ]
    for url in urls:
        for kind, http in clients.items():
            response = visit(http, "get", url)
            if kind == "owner":
                assert response.status_code == 200, url
            elif kind == "anon":
                assert response.status_code == 302, url
            else:
                assert response.status_code in (302, 403), (url, kind)
                if response.status_code == 302:
                    assert "/control/login/" in response["Location"], (url, kind)
