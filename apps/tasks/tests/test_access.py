import pytest
from django.urls import reverse

from apps.accounts.tests.factories import manager, owner, portal_user, sign_in, staff
from apps.clients.tests.factories import ClientFactory

from .factories import accounts_client, make_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    client_row = accounts_client()
    task = make_task(owner(), title="Sample", client=client_row)
    from apps.tasks.models import (
        Project,
        ProjectSection,
        RepeatingTask,
        TaskCategory,
        TaskStatus,
        TaskTemplate,
    )

    project = Project.objects.create(name="Access project")
    repeating_rule = RepeatingTask.objects.create(
        title="Access rule", frequency="weekly", first_date=task.created_at.date()
    )
    return {
        "project": project,
        "section": ProjectSection.objects.create(project=project, name="One"),
        "rule": repeating_rule,
        "task": task,
        "client": client_row,
        "step": client_row.tasks.first().steps.first(),
        "status": TaskStatus.objects.first(),
        "category": TaskCategory.objects.first(),
        "template": TaskTemplate.objects.first(),
        "service": TaskTemplate.objects.first().service,
    }


def staff_addresses(w):
    t, c = w["task"].pk, w["client"].pk
    return [
        ("overview", [], "get"),
        ("tasks:list", [], "get"),
        ("tasks:new", [], "get"),
        ("tasks:new", [], "post"),
        ("tasks:client_options", [], "get"),
        ("tasks:bulk", [], "post"),
        ("tasks:view_save", [], "post"),
        ("tasks:view_default", [1], "post"),
        ("tasks:view_delete", [1], "post"),
        ("tasks:detail", [t], "get"),
        ("tasks:field", [t, "owner"], "post"),
        ("tasks:complete", [t], "post"),
        ("tasks:cancel", [t], "post"),
        ("tasks:star", [t], "post"),
        ("tasks:follow", [t], "post"),
        ("tasks:step_pick", [t], "post"),
        ("tasks:step", [w["step"].task_id, w["step"].pk], "post"),
        ("tasks:comment", [t], "post"),
        ("tasks:description", [t], "get"),
        ("tasks:description", [t], "post"),
        ("tasks:attach", [t], "post"),
        ("tasks:client_tasks", [c], "get"),
        ("tasks:board_move", [], "post"),
        ("tasks:calendar_move", [], "post"),
        ("tasks:projects", [], "get"),
        ("tasks:project_new", [], "get"),
        ("tasks:project_new", [], "post"),
        ("tasks:project", [w["project"].pk], "get"),
        ("tasks:project_edit", [w["project"].pk], "get"),
        ("tasks:project_edit", [w["project"].pk], "post"),
        ("tasks:project_section_add", [w["project"].pk], "post"),
        ("tasks:repeating", [], "get"),
        ("tasks:repeating_new", [], "get"),
        ("tasks:repeating_new", [], "post"),
        ("tasks:repeating_edit", [w["rule"].pk], "get"),
        ("tasks:repeating_toggle", [w["rule"].pk], "post"),
        ("tasks:workload", [], "get"),
    ]


def settings_addresses(w):
    s, c, tpl, svc = w["status"].pk, w["category"].pk, w["template"].pk, w["service"].pk
    return [
        ("tasks:statuses", [], "get"),
        ("tasks:status_add", [], "get"),
        ("tasks:status_add", [], "post"),
        ("tasks:status_edit", [s], "get"),
        ("tasks:status_delete", [s], "post"),
        ("tasks:status_move", [s, "up"], "post"),
        ("tasks:status_merge", [s], "get"),
        ("tasks:categories", [], "get"),
        ("tasks:category_add", [], "get"),
        ("tasks:category_edit", [c], "get"),
        ("tasks:category_delete", [c], "post"),
        ("tasks:category_move", [c, "down"], "post"),
        ("tasks:category_merge", [c], "get"),
        ("tasks:service_templates", [svc], "get"),
        ("tasks:template_add", [svc], "get"),
        ("tasks:template_edit", [tpl], "get"),
    ]


def call(client, name, args, method):
    return getattr(client, method)(reverse(name, args=args))


def test_every_address_sends_signed_out_users_to_sign_in(client, world):
    for name, args, method in staff_addresses(world) + settings_addresses(world):
        response = call(client, name, args, method)
        assert response.status_code == 302, name
        assert "/login/" in response["Location"], name


def test_every_address_refuses_portal_users(client, world):
    sign_in(client, portal_user())
    for name, args, method in staff_addresses(world) + settings_addresses(world):
        assert call(client, name, args, method).status_code == 403, name


def test_settings_need_the_settings_right(client, world):
    sign_in(client, staff())
    for name, args, method in settings_addresses(world):
        assert call(client, name, args, method).status_code == 403, name
    assert client.get(reverse("tasks:list")).status_code == 200


@pytest.mark.parametrize("who", [owner, manager])
def test_settings_open_for_owner_and_manager(client, world, who):
    sign_in(client, who())
    for name, args, method in settings_addresses(world):
        if method == "get":
            assert call(client, name, args, method).status_code == 200, name


def test_everyone_on_staff_sees_every_task(client, world):
    sign_in(client, staff())
    assert "Sample" in client.get(reverse("tasks:list")).content.decode()
    assert client.get(reverse("tasks:detail", args=[world["task"].pk])).status_code == 200


def test_the_client_tab_works_for_any_client(client, world):
    sign_in(client, staff())
    other = ClientFactory()
    assert client.get(reverse("tasks:client_tasks", args=[other.pk])).status_code == 200
    assert client.get(reverse("tasks:client_tasks", args=[999999])).status_code == 404


def test_the_tasks_tab_is_on_the_client_page(client, world):
    sign_in(client, staff())
    html = client.get(reverse("clients:detail", args=[world["client"].pk])).content.decode()
    assert reverse("tasks:client_tasks", args=[world["client"].pk]) in html


def test_tasks_are_in_the_navigation(client):
    sign_in(client, staff())
    html = client.get(reverse("overview")).content.decode()
    assert reverse("tasks:list") in html and "Overview" in html


def test_the_board_and_calendar_pages_need_a_staff_sign_in(client, world):
    for layout in ("board", "calendar"):
        response = client.get(reverse("tasks:list") + f"?layout={layout}")
        assert response.status_code == 302 and "/login/" in response["Location"]
    sign_in(client, portal_user())
    for layout in ("board", "calendar"):
        assert client.get(reverse("tasks:list") + f"?layout={layout}").status_code == 403


def test_every_staff_member_can_use_the_new_pages(client, world):
    sign_in(client, staff())
    for name, args in (
        ("tasks:projects", []),
        ("tasks:project", [world["project"].pk]),
        ("tasks:repeating", []),
        ("tasks:workload", []),
        ("overview", []),
    ):
        assert client.get(reverse(name, args=args)).status_code == 200, name
    assert client.get(reverse("tasks:project", args=[999999])).status_code == 404
    assert client.get(reverse("tasks:list") + "?layout=board").status_code == 200
    assert client.get(reverse("tasks:list") + "?layout=calendar&date=nonsense").status_code == 200


def test_moves_refuse_get_requests(client, world):
    sign_in(client, staff())
    assert client.get(reverse("tasks:board_move")).status_code == 405
    assert client.get(reverse("tasks:calendar_move")).status_code == 405
