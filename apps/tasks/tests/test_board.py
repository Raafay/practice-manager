from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import owner, sign_in, staff
from apps.clients.tests.factories import ClientFactory
from apps.events.models import ActivityEvent
from apps.tasks import board, services
from apps.tasks.models import Project, ProjectSection, Task

from .factories import accounts_client, category, make_task, status

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def move(client, task, by, to, before="", after=""):
    return client.post(
        reverse("tasks:board_move"),
        {"task": task.pk, "by": by, "to": to, "before": before, "after": after},
    )


def events_for(task):
    return ActivityEvent.objects.filter(target_id=str(task.pk), verb__startswith="task.")


@pytest.fixture
def me(client):
    user = owner(name="Ann Owner")
    sign_in(client, user)
    return user


def test_a_status_move_changes_the_status_and_writes_one_event(client, me):
    task = make_task(me, title="Move me")
    before = events_for(task).count()
    response = move(client, task, "status", status("In progress").pk)
    assert response.status_code == 200 and f"card-{task.pk}" in response.content.decode()
    task.refresh_from_db()
    assert task.status == status("In progress")
    assert events_for(task).count() == before + 1
    assert events_for(task).order_by("-id").first().verb == "task.status_changed"


def test_an_owner_move_assigns_and_the_none_column_unassigns(client, me):
    other = staff(name="Bob Staff")
    task = make_task(me, title="Hand over", owner=me)
    move(client, task, "owner", other.pk)
    task.refresh_from_db()
    assert task.owner == other
    count = events_for(task).count()
    move(client, task, "owner", "none")
    task.refresh_from_db()
    assert task.owner is None and events_for(task).count() == count + 1


def test_a_category_move_changes_the_category(client, me):
    task = make_task(me, title="Sort me", category=category("Insurance"))
    move(client, task, "category", category("Operations").pk)
    task.refresh_from_db()
    assert task.category == category("Operations")
    assert events_for(task).order_by("-id").first().verb == "task.category_changed"


def test_a_client_move_changes_the_client_and_writes_one_event(client, me):
    first, second = ClientFactory(name="First Ltd"), ClientFactory(name="Second Ltd")
    task = make_task(me, title="Whose job", client=first)
    before = events_for(task).count()
    assert move(client, task, "client", second.pk).status_code == 200
    task.refresh_from_db()
    assert task.client == second and events_for(task).count() == before + 1
    move(client, task, "client", "none")
    task.refresh_from_db()
    assert task.client is None


def test_a_task_from_a_deadline_cannot_change_client(client, me):
    owner_client = accounts_client()
    generated = owner_client.tasks.first()
    other = ClientFactory()
    response = move(client, generated, "client", other.pk)
    assert response.status_code == 422 and "deadline" in response.content.decode()
    generated.refresh_from_db()
    assert generated.client == owner_client


def test_a_section_move_stays_inside_the_project(client, me):
    project = Project.objects.create(name="Health check")
    other = Project.objects.create(name="Other")
    one = ProjectSection.objects.create(project=project, name="One")
    two = ProjectSection.objects.create(project=project, name="Two")
    stray = ProjectSection.objects.create(project=other, name="Stray")
    task = make_task(me, title="In a project", project=project, section=one)
    assert move(client, task, "section", two.pk).status_code == 200
    task.refresh_from_db()
    assert task.section == two
    assert move(client, task, "section", stray.pk).status_code == 422
    task.refresh_from_db()
    assert task.section == two


def test_reordering_in_a_column_changes_only_the_moved_card_and_writes_no_event(client, me):
    a, b, c = (make_task(me, title=name) for name in "ABC")
    Task.objects.filter(pk=a.pk).update(position=1024)
    Task.objects.filter(pk=b.pk).update(position=2048)
    Task.objects.filter(pk=c.pk).update(position=3072)
    count = ActivityEvent.objects.count()
    response = move(client, c, "status", a.status_id, before=a.pk, after=b.pk)
    assert response.status_code == 200
    for task in (a, b, c):
        task.refresh_from_db()
    assert (a.position, b.position, c.position) == (1024, 2048, 1536)
    assert ActivityEvent.objects.count() == count
    column = Task.objects.filter(status=a.status).order_by(*board.card_order())
    assert [t.title for t in column] == ["A", "C", "B"]


def test_cards_with_no_room_between_them_are_renumbered_once(client, me):
    a, b, c = (make_task(me, title=name) for name in "ABC")  # all position 0
    move(client, c, "status", a.status_id, before=a.pk, after=b.pk)
    column = list(Task.objects.filter(status=a.status).order_by(*board.card_order()))
    assert [t.title for t in column][:3] == ["A", "C", "B"]
    assert len({t.position for t in column}) == 3


def test_a_card_can_go_to_the_top_or_the_bottom_of_a_column(client, me):
    a, b, c = (make_task(me, title=name) for name in "ABC")
    move(client, c, "status", a.status_id, after=a.pk)  # to the top
    order = lambda: [  # noqa: E731
        t.title for t in Task.objects.filter(status=a.status).order_by(*board.card_order())
    ]
    assert order()[0] == "C"
    move(client, c, "status", a.status_id, before=b.pk)  # to the bottom
    assert order()[-1] == "C"


def test_a_failed_move_changes_nothing_and_says_why(client, me):
    task = make_task(me, title="Stay put")
    count = ActivityEvent.objects.count()
    response = move(client, task, "status", 999999)
    assert response.status_code == 422 and "does not exist" in response.content.decode()
    response = move(client, task, "nonsense", 1)
    assert response.status_code == 422
    task.refresh_from_db()
    assert task.status == status("To do") and ActivityEvent.objects.count() == count


def test_a_cancelled_task_cannot_be_moved(client, me):
    task = make_task(me, title="Gone")
    services.cancel(me, task)
    assert move(client, task, "status", status("In progress").pk).status_code == 422


def test_the_done_column_shows_only_the_last_14_days():
    user = owner()
    recent, old, open_one = (make_task(user, title=n) for n in ("Recent", "Old", "Open"))
    services.complete(user, recent)
    services.complete(user, old)
    Task.objects.filter(pk=old.pk).update(completed_at=timezone.now() - timedelta(days=20))
    Task.objects.filter(pk=recent.pk).update(completed_at=timezone.now() - timedelta(days=13))
    data = board.build(Task.objects.live(), "status")
    by_name = {c.label: [t.title for t in c.tasks] for c in data["columns"]}
    assert by_name["Done"] == ["Recent"]
    assert by_name["To do"] == ["Open"]
    done = next(c for c in data["columns"] if c.label == "Done")
    assert done.note == "Last 14 days"


def test_the_board_page_has_columns_cards_counts_and_the_other_modes(client, me):
    make_task(me, title="Card one", owner=me)
    make_task(me, title="Card two")
    html = client.get(reverse("tasks:list") + "?layout=board").content.decode()
    assert 'data-board="status"' in html and "Card one" in html and "data-card" in html
    assert 'data-column-key="none"' not in html  # status columns have no empty column
    html = client.get(reverse("tasks:list") + "?layout=board&by=owner").content.decode()
    assert 'data-board="owner"' in html and 'data-column-key="none"' in html
    assert "Unassigned" in html
    html = client.get(reverse("tasks:list") + "?layout=board&by=section").content.decode()
    assert 'data-board="status"' in html  # sections only make sense inside a project


def test_the_board_uses_the_same_filters_and_chips_as_the_table(client, me):
    make_task(me, title="Mine", owner=me)
    make_task(me, title="Not mine")
    html = client.get(reverse("tasks:list") + "?layout=board&chip=mine").content.decode()
    assert "Mine" in html and "Not mine" not in html


def test_board_card_shows_step_progress(client, me):
    task = make_task(me, title="With steps")
    from apps.tasks.models import TaskStep

    TaskStep.objects.create(task=task, name="One", position=1)
    TaskStep.objects.create(task=task, name="Two", position=2)
    services.toggle_step(me, task.steps.first(), done=True)
    html = client.get(reverse("tasks:list") + "?layout=board").content.decode()
    assert ">1/2<" in html
