from datetime import timedelta

import pytest
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Team
from apps.accounts.tests.factories import owner, sign_in, staff
from apps.clients.tests.factories import ClientFactory
from apps.services.models import Service
from apps.tasks import filters, listing, services
from apps.tasks.models import Task, TaskKind

from .factories import category, make_task, status

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def days(n):
    return TODAY + timedelta(days=n)


@pytest.fixture
def me():
    return owner(name="Mina Test")


@pytest.fixture
def world(me):
    other = staff(name="Otto Other")
    client_a = ClientFactory(name="Acorn Ltd", manager=other)
    client_b = ClientFactory(name="Birch Ltd")
    service = Service.objects.get(code="vat")
    return {
        "me": me,
        "other": other,
        "a": client_a,
        "b": client_b,
        "compliance": make_task(
            me,
            title="VAT for Acorn",
            client=client_a,
            kind=TaskKind.COMPLIANCE,
            owner=me,
            category=category("VAT"),
            service=service,
            due_date=days(3),
            target_date=days(1),
        ),
        "fractional": make_task(
            me,
            title="Cash flow review",
            client=client_b,
            kind=TaskKind.ADVISORY,
            owner=other,
            category=category("Cash flow and funding"),
            target_date=days(30),
        ),
        "request": make_task(
            me,
            title="Client asked for a letter",
            client=client_a,
            kind=TaskKind.REQUEST,
            owner=None,
            due_date=days(10),
        ),
        "overdue": make_task(
            me,
            title="Late thing",
            client=client_b,
            kind=TaskKind.INTERNAL,
            owner=me,
            target_date=days(-3),
        ),
        "nodate": make_task(me, title="No dates at all", kind=TaskKind.INTERNAL, owner=None),
    }


def titles(user, **params):
    query, _ = filters.parse(QueryDict("", mutable=True) if not params else _qd(params))
    return [t.title for t in filters.apply(query, user).order_by(*filters.ordering_for(query.sort))]


def _qd(params):
    q = QueryDict(mutable=True)
    for key, value in params.items():
        q[key] = value
    return q


def names(world, *keys):
    return sorted(world[k].title for k in keys)


# ------------------------------------------------------------------ chips


@pytest.mark.parametrize(
    ("chip", "expected"),
    [
        ("all", ["compliance", "fractional", "request", "overdue", "nodate"]),
        ("compliance", ["compliance"]),
        ("fractional", ["fractional"]),
        ("requests", ["request"]),
        ("mine", ["compliance", "overdue"]),
        ("unassigned", ["request", "nodate"]),
        ("overdue", ["overdue"]),
    ],
)
def test_each_quick_chip(world, chip, expected):
    assert sorted(titles(world["me"], chip=chip)) == names(world, *expected)


def test_this_week_chip_uses_target_or_deadline_in_the_current_week():
    me = owner()
    first, last = filters.week_bounds(TODAY)
    inside = make_task(me, title="In week", target_date=first)
    also = make_task(me, title="Deadline in week", due_date=last)
    make_task(me, title="Next week", target_date=last + timedelta(days=1))
    make_task(me, title="Last week", target_date=first - timedelta(days=1))
    assert sorted(titles(me, chip="this_week")) == sorted([inside.title, also.title])


def test_done_tasks_are_hidden_until_show_done(world):
    services.complete(world["me"], world["compliance"])
    assert "VAT for Acorn" not in titles(world["me"])
    assert "VAT for Acorn" in titles(world["me"], show_done="1")


def test_cancelled_tasks_never_show(world):
    services.cancel(world["me"], world["nodate"])
    assert "No dates at all" not in titles(world["me"], show_done="1")


# ------------------------------------------------------------------ filters


def test_owner_filter(world):
    me, other = world["me"], world["other"]
    assert sorted(titles(me, owner=str(other.pk))) == names(world, "fractional")
    assert sorted(titles(me, owner="none")) == names(world, "request", "nodate")


def test_client_filter_by_number_and_by_name(world):
    me = world["me"]
    both = names(world, "compliance", "request")
    assert sorted(titles(me, client=str(world["a"].pk))) == both
    assert sorted(titles(me, client="acorn")) == both
    assert sorted(titles(me, client=world["a"].reference)) == both


def test_manager_of_the_client_filter(world):
    assert sorted(titles(world["me"], manager=str(world["other"].pk))) == names(
        world, "compliance", "request"
    )


def test_team_filter(world):
    team = Team.objects.create(name="North")
    Task.objects.filter(pk=world["overdue"].pk).update(team=team)
    assert titles(world["me"], team=str(team.pk)) == ["Late thing"]


def test_kind_category_service_status_priority_filters(world):
    me = world["me"]
    assert titles(me, kind="advisory") == ["Cash flow review"]
    assert titles(me, category=str(category("VAT").pk)) == ["VAT for Acorn"]
    assert titles(me, service=str(Service.objects.get(code="vat").pk)) == ["VAT for Acorn"]
    services.set_field(me, world["nodate"], "status", status("In review"))
    assert titles(me, status=str(status("In review").pk)) == ["No dates at all"]
    services.set_field(me, world["request"], "priority", "urgent")
    assert titles(me, priority="urgent") == ["Client asked for a letter"]


def test_project_filter(world):
    Task.objects.filter(pk=world["request"].pk).update(project_id=7)
    assert titles(world["me"], project="7") == ["Client asked for a letter"]


def test_starred_filter_is_per_user(world):
    me, other = world["me"], world["other"]
    services.toggle_star(me, world["fractional"])
    assert titles(me, starred="on") == ["Cash flow review"]
    assert titles(other, starred="on") == []


def test_date_range_on_target_or_deadline(world):
    me = world["me"]
    assert titles(me, date_from=days(20).isoformat()) == ["Cash flow review"]
    assert sorted(
        titles(me, date_from=days(2).isoformat(), date_to=days(5).isoformat(), date_field="due")
    ) == ["VAT for Acorn"]
    assert titles(me, date_to=days(-1).isoformat()) == ["Late thing"]


def test_text_search_matches_title_client_and_period(world):
    me = world["me"]
    assert titles(me, q="cash") == ["Cash flow review"]
    assert sorted(titles(me, q="acorn")) == names(world, "compliance", "request")
    assert titles(me, q="cash birch") == ["Cash flow review"]


def test_bad_filter_values_are_ignored_not_errors(world):
    assert len(titles(world["me"], owner="x", team="999", status="abc", date_from="nonsense")) == 5


# ------------------------------------------------------------------ sort and grouping


def test_default_sort_is_deadline_soonest_with_empty_last(world):
    result = titles(world["me"])
    assert result[:2] == ["VAT for Acorn", "Client asked for a letter"]
    # Tasks without a deadline follow, by target date, with no-date tasks last.
    assert result[-1] == "No dates at all"


def test_sort_by_name_and_reverse_and_empty_dates_last_both_ways(world):
    me = world["me"]
    assert titles(me, sort="name")[0] == "Cash flow review"
    assert titles(me, sort="-name")[0] == "VAT for Acorn"
    assert titles(me, sort="target")[-1] == "No dates at all"
    assert titles(me, sort="-target")[-1] == "No dates at all"
    assert titles(me, sort="-target")[0] == "Cash flow review"


@pytest.mark.parametrize("sort", list(filters.SORTS))
def test_every_column_sorts(world, sort):
    assert len(titles(world["me"], sort=sort)) == 5
    assert len(titles(world["me"], sort=f"-{sort}")) == 5


def build(world, **params):
    request_params = _qd(params)
    query, _ = filters.parse(request_params)
    queryset = filters.apply(query, world["me"])
    return listing.build(queryset, query, new_url="/tasks/new/")


@pytest.mark.parametrize(
    ("mode", "labels"),
    [
        ("client", ["Acorn Ltd", "Birch Ltd", "No client"]),
        ("owner", ["Mina Test", "Otto Other", "Unassigned"]),
        ("status", ["To do"]),
        ("category", ["Cash flow and funding", "VAT", "No category"]),
        ("service", ["VAT Returns", "No service"]),
    ],
)
def test_grouping(world, mode, labels):
    result = build(world, group=mode)
    assert [g.label for g in result["groups"]] == labels
    assert sum(g.total for g in result["groups"]) == 5


def test_group_by_week_due(world):
    result = build(world, group="week")
    assert result["groups"][-1].label == "No date"
    assert all(g.label.startswith("Week of") for g in result["groups"][:-1])


def test_each_group_has_an_add_task_row_with_its_values(world):
    result = build(world, group="client")
    acorn = result["groups"][0]
    assert acorn.add_url == f"/tasks/new/?client={world['a'].pk}"
    by_owner = build(world, group="owner")["groups"][1]
    assert f"owner={world['other'].pk}" in by_owner.add_url


def test_limits_per_group_and_in_all():
    me = owner()
    client = ClientFactory()
    todo = status("To do")
    Task.objects.bulk_create(
        Task(title=f"T{i}", client=client, status=todo, kind="advisory", owner=me)
        for i in range(260)
    )
    query, _ = filters.parse(QueryDict(""))
    queryset = filters.apply(query, me)
    first = listing.build(queryset, query)
    assert len(first["groups"][0].tasks) == 200 and first["more"]
    second = listing.build(queryset, query, page=2)
    assert len(second["groups"][0].tasks) == 260 and not second["more"]

    grouped, _ = filters.parse(_qd({"group": "client"}))
    result = listing.build(filters.apply(grouped, me), grouped)
    assert len(result["groups"][0].tasks) == 50 and result["more"]
    assert result["groups"][0].hidden == 210


def test_the_table_stays_quick_with_two_thousand_tasks(client, django_assert_max_num_queries):
    me = owner()
    sign_in(client, me)
    todo = status("To do")
    clients = [ClientFactory() for _ in range(5)]
    Task.objects.bulk_create(
        Task(
            title=f"T{i}",
            client=clients[i % 5],
            status=todo,
            kind="advisory",
            owner=me,
            due_date=days(i % 40),
        )
        for i in range(2000)
    )
    url = reverse("tasks:list")
    for params in ("", "?group=client", "?group=owner&sort=-name", "?chip=mine&group=week"):
        with django_assert_max_num_queries(30):
            response = client.get(url + params)
        assert response.status_code == 200


def test_query_count_does_not_grow_with_the_rows(client, django_assert_num_queries):
    me = owner()
    sign_in(client, me)
    todo = status("To do")
    rows = [Task(title=f"T{i}", status=todo, kind="advisory", owner=me) for i in range(10)]
    Task.objects.bulk_create(rows)
    client.get(reverse("tasks:list"))
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as small:
        client.get(reverse("tasks:list"))
    Task.objects.bulk_create(
        Task(title=f"U{i}", status=todo, kind="advisory", owner=me) for i in range(150)
    )
    with CaptureQueriesContext(connection) as large:
        client.get(reverse("tasks:list"))
    assert len(large) == len(small)


# ------------------------------------------------------------------ the page itself


def test_page_shows_alert_latest_action_and_deadline_badge(client, world):
    me = world["me"]
    sign_in(client, me)
    task = world["compliance"]
    Task.objects.filter(pk=task.pk).update(target_date=days(-1))
    from apps.tasks.models import TaskStep

    step = TaskStep.objects.create(task=task, name="Records received", position=1)
    TaskStep.objects.create(task=task, name="Return prepared", position=2)
    services.toggle_step(me, step)
    html = client.get(reverse("tasks:list")).content.decode()
    assert "Needs attention" in html
    assert "Records received" in html and "No action yet" in html
    assert f"{days(3):%d/%m/%Y}" in html


def test_view_state_lives_in_the_address(client, world):
    sign_in(client, world["me"])
    html = client.get(reverse("tasks:list") + "?chip=mine&group=client&sort=-name").content.decode()
    assert 'aria-current="true"' in html
    assert 'name="chip" value="mine"' in html


def test_htmx_request_gets_the_partial(client, world):
    sign_in(client, world["me"])
    response = client.get(reverse("tasks:list"), HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert "<html" not in html and 'id="task-results"' in html
    assert "HX-Request" in response["Vary"]


def test_client_tab_is_fixed_to_the_client_and_hides_the_client_column(client, world):
    sign_in(client, world["me"])
    html = client.get(reverse("tasks:client_tasks", args=[world["a"].pk])).content.decode()
    assert "VAT for Acorn" in html and "Cash flow review" not in html
    assert "Add task" in html and f"client={world['a'].pk}" in html
    partial = client.get(
        reverse("tasks:client_tasks", args=[world["a"].pk]),
        HTTP_HX_REQUEST="true",
        HTTP_HX_TARGET="task-page",
    ).content.decode()
    assert 'id="task-results"' in partial and "<html" not in partial


def test_empty_list_says_what_to_do_next(client):
    sign_in(client, owner())
    assert "Clear the filters" in client.get(reverse("tasks:list")).content.decode()
