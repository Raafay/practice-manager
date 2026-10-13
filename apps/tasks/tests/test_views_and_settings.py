from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import owner, sign_in, staff
from apps.clients.models import SavedView
from apps.clients.tests.factories import ClientFactory
from apps.events.models import ActivityEvent
from apps.tasks import services
from apps.tasks.models import Task, TaskCategory, TaskStatus, TaskTemplate

from .factories import category, make_task, status

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def days(n):
    return TODAY + timedelta(days=n)


# ------------------------------------------------------------------ saved views


def save(client, name="Mine", query="chip=mine&group=client", **extra):
    return client.post(reverse("tasks:view_save"), {"name": name, "query": query, **extra})


def test_a_private_view_is_visible_only_to_its_owner(client):
    ann, bob = owner(name="Ann Owner"), staff(name="Bob Staff")
    sign_in(client, ann)
    save(client, "Ann's private")
    view = SavedView.objects.get()
    assert view.list_key == "tasks" and view.filters == {"qs": "chip=mine&group=client"}
    assert (
        "Ann&#x27;s private" in client.get(reverse("tasks:list")).content.decode()
        or "Ann's private" in client.get(reverse("tasks:list")).content.decode()
    )
    client.logout()
    sign_in(client, bob)
    html = client.get(reverse("tasks:list")).content.decode()
    assert "private" not in html
    response = client.get(reverse("tasks:list") + f"?view={view.pk}")
    assert 'name="chip"' not in response.content.decode()


def test_a_shared_view_is_visible_to_everyone_and_applies_its_query(client):
    ann, bob = owner(name="Ann Owner"), staff(name="Bob Staff")
    make_task(ann, title="Ann's task", owner=ann)
    make_task(ann, title="Unowned task", owner=None)
    sign_in(client, ann)
    save(client, "Unassigned work", "chip=unassigned", shared="on")
    view = SavedView.objects.get()
    client.logout()
    sign_in(client, bob)
    assert "Unassigned work" in client.get(reverse("tasks:list")).content.decode()
    html = client.get(reverse("tasks:list") + f"?view={view.pk}").content.decode()
    assert "Unowned task" in html and "Ann&#x27;s task" not in html


def test_a_view_needs_a_name(client):
    sign_in(client, owner())
    save(client, "")
    assert not SavedView.objects.exists()


def test_only_the_owner_or_the_practice_owner_may_delete_a_view(client):
    ann, bob, boss = staff(name="Ann Staff"), staff(name="Bob Staff"), owner()
    sign_in(client, ann)
    save(client, "Shared", "chip=mine", shared="on")
    view = SavedView.objects.get()
    client.logout()
    sign_in(client, bob)
    assert client.post(reverse("tasks:view_delete", args=[view.pk])).status_code == 403
    client.logout()
    sign_in(client, boss)
    assert client.post(reverse("tasks:view_delete", args=[view.pk])).status_code == 302
    assert not SavedView.objects.exists()


def test_a_client_view_cannot_be_reached_through_the_task_addresses(client):
    from apps.clients.tests.factories import ClientFactory as _  # noqa: F401

    boss = owner()
    clients_view = SavedView.objects.create(list_key="clients", name="Clients", owner=boss)
    sign_in(client, boss)
    assert client.post(reverse("tasks:view_delete", args=[clients_view.pk])).status_code == 404
    assert client.post(reverse("tasks:view_default", args=[clients_view.pk])).status_code == 404


def test_one_default_view_per_user_and_it_opens_first(client):
    ann = owner(name="Ann Owner")
    make_task(ann, title="Mine one", owner=ann)
    make_task(ann, title="Nobody's", owner=None)
    sign_in(client, ann)
    save(client, "First", "chip=mine")
    save(client, "Second", "chip=unassigned")
    first, second = SavedView.objects.order_by("pk")
    client.post(reverse("tasks:view_default", args=[first.pk]))
    client.post(reverse("tasks:view_default", args=[second.pk]))
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.is_default, second.is_default) == (False, True)
    html = client.get(reverse("tasks:list")).content.decode()
    assert "Nobody&#x27;s" in html and "Mine one" not in html
    # An address with its own query is not overridden.
    assert "Mine one" in client.get(reverse("tasks:list") + "?chip=mine").content.decode()
    client.post(reverse("tasks:view_default", args=[second.pk]))
    second.refresh_from_db()
    assert not second.is_default


def test_defaults_are_per_user(client):
    ann, bob = owner(name="Ann Owner"), staff(name="Bob Staff")
    sign_in(client, ann)
    save(client, "Shared", "chip=unassigned", shared="on")
    view = SavedView.objects.get()
    client.post(reverse("tasks:view_default", args=[view.pk]))
    client.logout()
    sign_in(client, bob)
    client.post(reverse("tasks:view_default", args=[view.pk]))
    assert SavedView.objects.filter(owner=bob, is_default=True).count() == 1
    assert SavedView.objects.filter(owner=ann, is_default=True).count() == 1
    assert SavedView.objects.filter(is_default=True).count() == 2


# ------------------------------------------------------------------ My work


def test_my_work_sections_and_unassigned_count(client):
    me = owner(name="Mina Test")
    sign_in(client, me)
    make_task(me, title="Late", owner=me, target_date=days(-2))
    make_task(me, title="Today's", owner=me, target_date=TODAY)
    nxt = make_task(me, title="Next month", owner=me, target_date=days(40))
    make_task(me, title="Undated", owner=me)
    waiting = make_task(me, title="Waiting one", owner=me, target_date=days(-5))
    services.set_field(me, waiting, "status", status("Waiting on client"))
    done = make_task(me, title="Finished", owner=me)
    services.complete(me, done)
    make_task(me, title="Someone else's", owner=staff())
    make_task(me, title="Nobody's A")
    make_task(me, title="Nobody's B")
    response = client.get(reverse("overview"))
    sections = {s["key"]: [t.title for t in s["tasks"]] for s in response.context["sections"]}
    assert sections["overdue"] == ["Late"]
    assert sections["today"] == ["Today's"]
    assert sections["waiting"] == ["Waiting one"]
    assert nxt.title in sections["later"] and "Undated" in sections["later"]
    assert "Finished" not in sum(sections.values(), []) and "Someone else's" not in sum(
        sections.values(), []
    )
    assert response.context["unassigned_count"] == 2
    assert "2</strong> unassigned tasks" in response.content.decode()


def test_my_work_is_empty_without_tasks(client):
    sign_in(client, staff())
    assert client.get(reverse("overview")).status_code == 200


# ------------------------------------------------------------------ settings


def test_a_status_in_use_cannot_be_deleted(client):
    boss = owner()
    sign_in(client, boss)
    make_task(boss, title="Uses it", status=status("In progress"))
    client.post(reverse("tasks:status_delete", args=[status("In progress").pk]))
    assert TaskStatus.objects.filter(name="In progress").exists()
    unused = TaskStatus.objects.create(name="Parked", position=99)
    client.post(reverse("tasks:status_delete", args=[unused.pk]))
    assert not TaskStatus.objects.filter(name="Parked").exists()
    client.post(reverse("tasks:status_delete", args=[status("To do").pk]))
    assert TaskStatus.objects.filter(name="To do").exists()  # the default stays


def test_a_category_in_use_cannot_be_deleted(client):
    boss = owner()
    sign_in(client, boss)
    make_task(boss, title="Uses it", category=category("VAT"))
    client.post(reverse("tasks:category_delete", args=[category("VAT").pk]))
    assert TaskCategory.objects.filter(name="VAT").exists()
    client.post(reverse("tasks:category_delete", args=[category("Practice admin").pk]))
    assert TaskCategory.objects.filter(name="Practice admin").exists() is False


def test_add_and_edit_a_status_and_the_default_moves(client):
    sign_in(client, owner())
    response = client.post(
        reverse("tasks:status_add"),
        {"name": "Blocked", "colour": "#dc2626", "is_done": "", "is_default": "on", "active": "on"},
    )
    assert response.status_code == 302
    assert TaskStatus.objects.get(is_default=True).name == "Blocked"
    assert TaskStatus.objects.filter(is_default=True).count() == 1
    bad = client.post(
        reverse("tasks:status_add"), {"name": "to do", "colour": "#000000", "active": "on"}
    )
    assert bad.status_code == 422
    bad = client.post(reverse("tasks:status_add"), {"name": "Odd", "colour": "red", "active": "on"})
    assert bad.status_code == 422


def test_there_must_always_be_a_done_status(client):
    sign_in(client, owner())
    done = status("Done")
    response = client.post(
        reverse("tasks:status_edit", args=[done.pk]),
        {"name": "Done", "colour": "#16a34a", "active": "on"},
    )
    assert response.status_code == 422
    done.refresh_from_db()
    assert done.is_done


def test_merging_a_status_moves_tasks_and_switches_it_off(client):
    boss = owner()
    sign_in(client, boss)
    task = make_task(boss, title="Moves", status=status("In review"))
    response = client.post(
        reverse("tasks:status_merge", args=[status("In review").pk]),
        {"into": status("In progress").pk},
    )
    assert response.status_code == 302
    task.refresh_from_db()
    assert task.status.name == "In progress"
    assert not TaskStatus.objects.get(name="In review").active
    assert ActivityEvent.objects.filter(verb="setting.changed", summary__contains="merged").exists()
    # A done status cannot be merged into one that is not done.
    bad = client.post(
        reverse("tasks:status_merge", args=[status("Done").pk]), {"into": status("To do").pk}
    )
    assert bad.status_code == 422


def test_merging_a_category(client):
    boss = owner()
    sign_in(client, boss)
    task = make_task(boss, title="Moves", category=category("Insurance"))
    client.post(
        reverse("tasks:category_merge", args=[category("Insurance").pk]),
        {"into": category("Other").pk},
    )
    task.refresh_from_db()
    assert task.category.name == "Other"
    assert not TaskCategory.objects.get(name="Insurance").active


def test_reordering_statuses(client):
    sign_in(client, owner())
    before = [s.name for s in TaskStatus.objects.all()]
    client.post(reverse("tasks:status_move", args=[status("In progress").pk, "up"]))
    after = [s.name for s in TaskStatus.objects.all()]
    assert after[:2] == [before[1], before[0]]


def test_settings_change_is_logged(client):
    sign_in(client, owner())
    client.post(
        reverse("tasks:category_add"),
        {"name": "Tax planning", "kind": "advisory", "colour": "#123456", "active": "on"},
    )
    assert ActivityEvent.objects.filter(
        verb="setting.changed", summary__contains="Tax planning"
    ).exists()


def test_the_templates_page_lists_templates_and_steps(client):
    sign_in(client, owner())
    template = TaskTemplate.objects.get(name_pattern__startswith="VAT Return")
    html = client.get(
        reverse("tasks:service_templates", args=[template.service_id])
    ).content.decode()
    assert "VAT Return Period End {period_end}" in html and "Records received" in html


def test_editing_a_template_and_its_steps(client):
    sign_in(client, owner())
    template = TaskTemplate.objects.get(name_pattern__startswith="VAT Return")
    steps = list(template.steps.all())
    data = {
        "rule": "vat_return",
        "name_pattern": "VAT Quarter {period_end}",
        "category": template.category_id,
        "default_owner": "partner",
        "target_kind": "days_before_due",
        "target_days": 10,
        "active": "on",
        "steps-TOTAL_FORMS": len(steps) + 1,
        "steps-INITIAL_FORMS": len(steps),
        "steps-MIN_NUM_FORMS": 0,
        "steps-MAX_NUM_FORMS": 1000,
    }
    for i, step in enumerate(steps):
        data.update(
            {
                f"steps-{i}-id": step.pk,
                f"steps-{i}-template": template.pk,
                f"steps-{i}-name": step.name,
                f"steps-{i}-position": step.position,
            }
        )
        if step.is_filing:
            data[f"steps-{i}-is_filing"] = "on"
    last = len(steps)
    data.update(
        {
            f"steps-{last}-name": "Partner sign-off",
            f"steps-{last}-position": 5,
            f"steps-{last}-template": template.pk,
        }
    )
    response = client.post(reverse("tasks:template_edit", args=[template.pk]), data)
    assert response.status_code == 302
    template.refresh_from_db()
    assert template.name_pattern == "VAT Quarter {period_end}" and template.target_days == 10
    assert template.default_owner == "partner"
    assert template.steps.filter(name="Partner sign-off").exists()


def test_a_template_name_may_only_use_known_fields(client):
    sign_in(client, owner())
    template = TaskTemplate.objects.get(name_pattern__startswith="VAT Return")
    data = {
        "rule": "vat_return",
        "name_pattern": "Oops {nothing}",
        "category": template.category_id,
        "default_owner": "manager",
        "target_kind": "days_before_due",
        "target_days": 7,
        "steps-TOTAL_FORMS": 0,
        "steps-INITIAL_FORMS": 0,
        "steps-MIN_NUM_FORMS": 0,
        "steps-MAX_NUM_FORMS": 1000,
    }
    response = client.post(reverse("tasks:template_edit", args=[template.pk]), data)
    assert response.status_code == 422
    assert "Use only" in response.content.decode()


def test_a_new_template_for_a_service(client):
    sign_in(client, owner())
    template = TaskTemplate.objects.get(name_pattern__startswith="VAT Return")
    data = {
        "rule": "vat_return",
        "name_pattern": "Extra VAT check {period_end}",
        "category": template.category_id,
        "default_owner": "nobody",
        "target_kind": "fixed_day",
        "target_month": 10,
        "target_day": 31,
        "target_days": 0,
        "active": "on",
        "steps-TOTAL_FORMS": 1,
        "steps-INITIAL_FORMS": 0,
        "steps-MIN_NUM_FORMS": 0,
        "steps-MAX_NUM_FORMS": 1000,
        "steps-0-name": "Check",
        "steps-0-position": 1,
    }
    client.post(reverse("tasks:template_add", args=[template.service_id]), data)
    assert TaskTemplate.objects.filter(name_pattern="Extra VAT check {period_end}").exists()


def test_a_fixed_day_template_needs_its_month_and_day(client):
    sign_in(client, owner())
    template = TaskTemplate.objects.get(name_pattern__startswith="VAT Return")
    data = {
        "rule": "vat_return",
        "name_pattern": "X {period_end}",
        "category": template.category_id,
        "default_owner": "manager",
        "target_kind": "fixed_day",
        "target_days": 0,
        "steps-TOTAL_FORMS": 0,
        "steps-INITIAL_FORMS": 0,
        "steps-MIN_NUM_FORMS": 0,
        "steps-MAX_NUM_FORMS": 1000,
    }
    assert (
        client.post(reverse("tasks:template_add", args=[template.service_id]), data).status_code
        == 422
    )


def test_seeded_statuses_categories_and_templates():
    assert list(TaskStatus.objects.values_list("name", flat=True)) == [
        "To do",
        "In progress",
        "Waiting on client",
        "In review",
        "Done",
    ]
    assert TaskStatus.objects.get(is_default=True).name == "To do"
    assert TaskStatus.objects.get(name="Waiting on client").is_waiting
    assert TaskCategory.objects.count() == 21
    assert TaskCategory.objects.filter(kind="advisory").count() == 10
    assert TaskTemplate.objects.count() == 16
    assert TaskTemplate.objects.get(name_pattern__startswith="CT600").steps.count() == 5
    sa = TaskTemplate.objects.get(name_pattern__startswith="Self Assessment")
    assert (sa.target_kind, sa.target_month, sa.target_day) == ("fixed_day", 10, 31)
    assert ClientFactory and Task
