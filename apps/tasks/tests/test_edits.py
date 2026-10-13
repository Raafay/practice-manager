from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.tests.factories import owner, sign_in, staff
from apps.clients.tests.factories import ClientFactory, DocumentFactory
from apps.events.models import ActivityEvent, Notification
from apps.tasks import services
from apps.tasks.models import Task, TaskDocument

from .factories import accounts_client, category, make_task, status

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def me():
    return owner(name="Sara Sample")


@pytest.fixture
def signed_in(client, me):
    sign_in(client, me)
    return client


@pytest.fixture
def task(me):
    return make_task(me, title="VAT Return Period End 30/09/2026", client=ClientFactory(), owner=me)


def field(client, task, name, value, **extra):
    return client.post(reverse("tasks:field", args=[task.pk, name]), {"value": value, **extra})


def events_for(task, verb=None):
    rows = ActivityEvent.objects.filter(target_id=str(task.pk), target_type__model="task")
    return rows.filter(verb=verb) if verb else rows


# ------------------------------------------------------------------ in-place edits write events


def test_status_change_returns_the_row_and_writes_a_readable_event(signed_in, task):
    response = field(signed_in, task, "status", status("In review").pk)
    assert response.status_code == 200
    assert f'id="task-row-{task.pk}"' in response.content.decode()
    task.refresh_from_db()
    assert task.status.name == "In review"
    event = events_for(task, "task.status_changed").get()
    assert event.summary == "Sara Sample moved VAT Return Period End 30/09/2026 to In review."
    assert event.client == task.client


def test_owner_and_target_date_edits_write_events(signed_in, task):
    other = staff(name="Otto Other")
    field(signed_in, task, "owner", other.pk)
    field(signed_in, task, "target_date", "2026-10-05")
    task.refresh_from_db()
    assert task.owner == other and str(task.target_date) == "2026-10-05"
    assert "assigned" in events_for(task, "task.owner_changed").get().summary
    assert "05/10/2026" in events_for(task, "task.target_date_changed").get().summary
    assert other in task.followers.all()


def test_unassigning_and_clearing_a_date(signed_in, task):
    field(signed_in, task, "owner", "")
    task.refresh_from_db()
    assert task.owner is None
    assert "unassigned" in events_for(task, "task.owner_changed").get().summary


def test_an_unchanged_value_writes_no_event(signed_in, task):
    field(signed_in, task, "status", task.status_id)
    assert not events_for(task, "task.status_changed").exists()


def test_bad_values_leave_the_task_alone_and_say_why(signed_in, task):
    response = field(signed_in, task, "owner", "9999")
    assert response.status_code == 422 and "Choose a value" in response.content.decode()
    assert field(signed_in, task, "target_date", "tomorrow").status_code == 422
    assert field(signed_in, task, "title", "   ").status_code == 422
    assert field(signed_in, task, "status", "").status_code == 422
    task.refresh_from_db()
    assert task.owner is not None and task.title.startswith("VAT")


def test_unknown_field_is_a_404(signed_in, task):
    assert field(signed_in, task, "client", "1").status_code == 404
    assert field(signed_in, task, "completed_at", "x").status_code == 404


def test_an_inactive_person_cannot_be_made_owner(signed_in, task):
    gone = staff(is_active=False)
    assert field(signed_in, task, "owner", gone.pk).status_code == 422


def test_drawer_edits_return_the_drawer(signed_in, task):
    response = field(signed_in, task, "priority", "urgent", view="drawer")
    assert 'id="task-title"' in response.content.decode()
    task.refresh_from_db()
    assert task.priority == "urgent"


def test_completing_sets_who_and_when_and_moving_back_clears_it(signed_in, task, me):
    signed_in.post(reverse("tasks:complete", args=[task.pk]))
    task.refresh_from_db()
    assert task.is_done and task.completed_by == me and task.completed_at
    field(signed_in, task, "status", status("In progress").pk)
    task.refresh_from_db()
    assert not task.is_done and task.completed_at is None


def test_cancel_hides_the_task_and_blocks_edits(signed_in, task):
    response = signed_in.post(reverse("tasks:cancel", args=[task.pk]))
    assert response.status_code == 302
    task.refresh_from_db()
    assert task.is_cancelled
    assert events_for(task, "task.cancelled").exists()
    assert field(signed_in, task, "owner", "").status_code == 422


def test_star_toggles_for_the_user_only(signed_in, task):
    signed_in.post(reverse("tasks:star", args=[task.pk]))
    assert task.stars.count() == 1
    signed_in.post(reverse("tasks:star", args=[task.pk]))
    assert task.stars.count() == 0


# ------------------------------------------------------------------ steps


def test_ticking_a_step_writes_an_event_and_updates_latest_action(signed_in, me):
    client = accounts_client()
    task = client.tasks.get(title__startswith="Accounts Preparation")
    step = task.steps.first()
    signed_in.post(reverse("tasks:step", args=[task.pk, step.pk]))
    step.refresh_from_db()
    assert step.done_at and step.done_by == me
    assert "ticked “Records requested”" in events_for(task, "task.step_done").get().summary
    signed_in.post(reverse("tasks:step", args=[task.pk, step.pk]))
    step.refresh_from_db()
    assert step.done_at is None and events_for(task, "task.step_undone").exists()


def test_the_latest_action_drop_down_ticks_the_chosen_step(signed_in):
    client = accounts_client()
    task = client.tasks.get(title__startswith="Accounts Preparation")
    third = task.steps.all()[2]
    signed_in.post(reverse("tasks:step_pick", args=[task.pk]), {"step": third.pk})
    third.refresh_from_db()
    assert third.done_at
    assert Task.objects.prefetch_related("steps").get(pk=task.pk).latest_action == third.name


def test_a_step_of_another_task_is_a_404(signed_in, task):
    other = accounts_client().tasks.first()
    response = signed_in.post(reverse("tasks:step", args=[task.pk, other.steps.first().pk]))
    assert response.status_code == 404


def test_filing_step_from_the_drawer_marks_the_deadline_done(signed_in, me):
    client = accounts_client()
    task = client.tasks.get(title__startswith="Companies House")
    signed_in.post(reverse("tasks:step", args=[task.pk, task.steps.get().pk]), {"view": "drawer"})
    assert client.deadlines.get(rule="ch_accounts").evidence == "Marked filed by Sara Sample"


# ------------------------------------------------------------------ comments, mentions, description


def test_comment_mentions_add_followers_and_notify(signed_in, task, me):
    otto = staff(name="Otto Other")
    pia = staff(name="Pia Person")
    signed_in.post(
        reverse("tasks:comment", args=[task.pk]), {"body": "Please look, @Otto Other and @pia."}
    )
    comment = task.comments.get()
    assert comment.author == me
    followers = set(task.followers.all())
    assert {otto, pia, me} <= followers
    assert Notification.objects.filter(user=otto, message__contains="mentioned you").count() == 1
    assert Notification.objects.filter(user=pia).count() == 1
    assert not Notification.objects.filter(user=me).exists()


def test_a_first_name_shared_by_two_people_mentions_nobody(signed_in, task):
    staff(name="Sam One")
    staff(name="Sam Two")
    signed_in.post(reverse("tasks:comment", args=[task.pk]), {"body": "Hi @Sam"})
    assert not Notification.objects.exists()


def test_empty_comment_is_refused(signed_in, task):
    response = signed_in.post(
        reverse("tasks:comment", args=[task.pk]), {"body": "  ", "view": "drawer"}
    )
    assert response.status_code == 422 and not task.comments.exists()


def test_comments_are_plain_text(signed_in, task):
    signed_in.post(reverse("tasks:comment", args=[task.pk]), {"body": "<script>alert(1)</script>"})
    html = signed_in.get(
        reverse("tasks:detail", args=[task.pk]), HTTP_HX_REQUEST="true"
    ).content.decode()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_description_is_cleaned_before_it_is_stored_and_shown(signed_in, task):
    dirty = (
        "<div>Hello <strong>there</strong><script>alert(1)</script>"
        '<a href="javascript:evil()" onclick="x()">link</a><img src=x onerror=y()></div>'
    )
    signed_in.post(reverse("tasks:description", args=[task.pk]), {"description": dirty})
    task.refresh_from_db()
    assert "<strong>there</strong>" in task.description
    for bad in ("<script", "javascript:", "onclick", "onerror", "<img"):
        assert bad not in task.description
    html = signed_in.get(
        reverse("tasks:detail", args=[task.pk]), HTTP_HX_REQUEST="true"
    ).content.decode()
    assert "<script>alert(1)" not in html
    assert events_for(task, "task.description_changed").exists()


def test_the_drawer_streams_comments_and_history_together(signed_in, task):
    field(signed_in, task, "status", status("In progress").pk)
    signed_in.post(reverse("tasks:comment", args=[task.pk]), {"body": "Chased the client."})
    html = signed_in.get(
        reverse("tasks:detail", args=[task.pk]), HTTP_HX_REQUEST="true"
    ).content.decode()
    assert "Chased the client." in html and "moved VAT Return Period End" in html


def test_drawer_banner_when_the_deadline_was_done_elsewhere(signed_in, me):
    from apps.services import deadlines

    client = accounts_client()
    task = client.tasks.first()
    deadlines.mark_done(me, client.deadlines.get(rule="ch_accounts"))
    html = signed_in.get(
        reverse("tasks:detail", args=[task.pk]), HTTP_HX_REQUEST="true"
    ).content.decode()
    assert "has been marked done" in html and "Complete this task" in html


def test_detail_at_its_own_address_shows_the_drawer_open_over_the_list(signed_in, task):
    html = signed_in.get(reverse("tasks:detail", args=[task.pk])).content.decode()
    assert "data-open-on-load" in html and 'id="task-title"' in html and 'id="task-page"' in html
    assert signed_in.get(reverse("tasks:detail", args=[999999])).status_code == 404


# ------------------------------------------------------------------ documents


def test_upload_attaches_a_client_document(signed_in, task):
    upload = SimpleUploadedFile("notes.txt", b"made up notes", content_type="text/plain")
    response = signed_in.post(reverse("tasks:attach", args=[task.pk]), {"file": upload})
    assert response.status_code == 302
    link = TaskDocument.objects.get(task=task)
    assert link.document.client == task.client and link.document.original_name == "notes.txt"
    assert events_for(task, "task.document_attached").exists()


def test_attach_an_existing_document_of_the_same_client_only(signed_in, task):
    mine = DocumentFactory(client=task.client)
    other = DocumentFactory()
    signed_in.post(reverse("tasks:attach", args=[task.pk]), {"document": mine.pk})
    signed_in.post(reverse("tasks:attach", args=[task.pk]), {"document": other.pk})
    assert list(task.attachments.values_list("document", flat=True)) == [mine.pk]


def test_a_task_without_a_client_takes_no_documents(signed_in, me):
    internal = make_task(me, title="Internal")
    upload = SimpleUploadedFile("a.txt", b"x", content_type="text/plain")
    signed_in.post(reverse("tasks:attach", args=[internal.pk]), {"file": upload})
    assert not TaskDocument.objects.exists()


def test_sensitive_documents_stay_behind_their_right(client, me):
    task = make_task(me, title="With docs", client=ClientFactory())
    secret = DocumentFactory(client=task.client, sensitive=True, title="Passport scan")
    services.attach_document(me, task, secret)
    person = staff(name="Plain Person")
    role = Role.objects.get(slug=Role.STAFF)
    role.rights = [r for r in role.rights if r != "documents.sensitive"]
    role.save()
    sign_in(client, person)
    html = client.get(
        reverse("tasks:detail", args=[task.pk]), HTTP_HX_REQUEST="true"
    ).content.decode()
    assert "(restricted)" in html
    assert str(secret.public_id) not in html
    assert (
        str(secret.public_id)
        not in client.get(reverse("tasks:detail", args=[task.pk])).content.decode()
    )


# ------------------------------------------------------------------ new task


def new(client, **data):
    data.setdefault("title", "Review the cash forecast")
    data.setdefault("kind", "advisory")
    return client.post(reverse("tasks:new"), data)


def test_new_task_from_the_form(signed_in, me):
    client_row = ClientFactory(name="Ashby Ltd")
    response = new(
        signed_in,
        client_text=f"Ashby Ltd ({client_row.reference})",
        category=category("Cash flow and funding").pk,
        owner=me.pk,
        target_date=(TODAY + timedelta(days=7)).isoformat(),
        description="<div>Look at <strong>March</strong></div><script>x()</script>",
    )
    assert response.status_code == 302
    task = Task.objects.get(title="Review the cash forecast")
    assert task.client == client_row and task.owner == me and task.kind == "advisory"
    assert task.status == status("To do") and task.source == "manual" and task.created_by == me
    assert "<script" not in task.description and "<strong>" in task.description
    assert events_for(task, "task.created").exists()
    assert response["Location"] == reverse("tasks:detail", args=[task.pk])


def test_new_task_without_a_client_or_owner(signed_in):
    new(signed_in, owner="")
    task = Task.objects.get()
    assert task.client is None and task.owner is None


def test_new_task_needs_a_title_and_a_real_client(signed_in):
    assert new(signed_in, title="").status_code == 422
    assert new(signed_in, client_text="Nobody Ltd").status_code == 422
    assert not Task.objects.exists()


def test_new_task_form_is_filled_from_the_address(signed_in, me):
    client_row = ClientFactory(name="Prefill Ltd")
    html = signed_in.get(
        reverse("tasks:new") + f"?client={client_row.pk}&category={category('VAT').pk}",
        HTTP_HX_REQUEST="true",
    ).content.decode()
    assert f"Prefill Ltd ({client_row.reference})" in html
    assert f'<option value="{category("VAT").pk}" selected>' in html


def test_client_options_for_the_search_box(signed_in):
    ClientFactory(name="Zebra Stripes Ltd")
    html = signed_in.get(reverse("tasks:client_options"), {"client_text": "zebra"}).content.decode()
    assert "Zebra Stripes Ltd" in html
    assert (
        signed_in.get(reverse("tasks:client_options"), {"client_text": "z"})
        .content.decode()
        .strip()
        == ""
    )


# ------------------------------------------------------------------ bulk


def test_bulk_actions(signed_in, me):
    other = staff(name="Otto Other")
    tasks = [make_task(me, title=f"Bulk {i}", owner=me) for i in range(3)]
    ids = [t.pk for t in tasks]
    url = reverse("tasks:bulk")
    signed_in.post(url, {"ids": ids, "action": "owner", "owner": other.pk})
    assert set(Task.objects.filter(pk__in=ids).values_list("owner", flat=True)) == {other.pk}
    signed_in.post(url, {"ids": ids, "action": "status", "status": status("In review").pk})
    assert set(Task.objects.filter(pk__in=ids).values_list("status__name", flat=True)) == {
        "In review"
    }
    signed_in.post(url, {"ids": ids, "action": "target_date", "target_date": "2026-11-02"})
    assert {
        str(d) for d in Task.objects.filter(pk__in=ids).values_list("target_date", flat=True)
    } == {"2026-11-02"}
    signed_in.post(url, {"ids": ids[:2], "action": "complete"})
    assert Task.objects.filter(pk__in=ids, status__is_done=True).count() == 2
    signed_in.post(url, {"ids": ids[2:], "action": "cancel"})
    assert Task.objects.get(pk=ids[2]).is_cancelled
    assert ActivityEvent.objects.filter(verb="task.owner_changed").count() == 3


def test_bulk_with_nothing_ticked_or_a_bad_action_changes_nothing(signed_in, me):
    task = make_task(me, title="Safe", owner=me)
    url = reverse("tasks:bulk")
    assert signed_in.post(url, {"action": "complete"}).status_code == 302
    signed_in.post(url, {"ids": [task.pk], "action": "delete"})
    signed_in.post(url, {"ids": [task.pk], "action": "owner", "owner": "9999"})
    task.refresh_from_db()
    assert task.owner == me and not task.is_done


def test_bulk_will_not_redirect_off_site(signed_in, me):
    task = make_task(me, title="Safe")
    response = signed_in.post(
        reverse("tasks:bulk"),
        {"ids": [task.pk], "action": "complete", "next": "https://evil.example/"},
    )
    assert response["Location"] == reverse("tasks:list")
