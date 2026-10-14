import dataclasses
from datetime import date, datetime

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Exists, OuterRef, Q
from django.http import Http404, HttpResponse, QueryDict
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps import events
from apps.accounts.models import Team, User
from apps.clients.forms import SavedViewForm
from apps.clients.models import Client, Contact, Document, SavedView
from apps.clients.services import can_open_document
from apps.clients.views import ClientTabView
from apps.clients.views_base import done, get_client, render_form, respond, wants_partial
from apps.core.permissions import StaffRequiredMixin
from apps.events.models import ActivityEvent

from . import board as board_mod
from . import calview, filters, listing, services
from .forms import CommentForm, TaskCreateForm, client_label
from .models import Project, ProjectSection, Task, TaskCategory, TaskKind, TaskStar, TaskStatus

LIST_KEY = "tasks"


# ------------------------------------------------------------------ shared pieces


def staff_people():
    return list(User.objects.staff().filter(is_active=True).order_by("name"))


def get_task(request, pk) -> Task:
    """One task with what the row and the drawer need."""
    queryset = (
        Task.objects.annotate(
            is_starred=Exists(TaskStar.objects.filter(task=OuterRef("pk"), user=request.user))
        )
        .select_related("client", "status", "owner", "reviewer", "category", "team", "deadline")
        .prefetch_related("steps")
    )
    return get_object_or_404(queryset, pk=pk)


def pick_lists() -> dict:
    return {
        "people": staff_people(),
        "statuses": list(TaskStatus.objects.filter(active=True)),
        "categories": list(TaskCategory.objects.filter(active=True)),
    }


def row_context(request, task: Task, error: str = "") -> dict:
    listing.decorate([task], timezone.localdate())
    return {"task": task, "row_error": error, "user": request.user, **pick_lists()}


def list_params(request) -> tuple[QueryDict, SavedView | None]:
    """The request's own query, a saved view's, or the user's default view."""
    view_id = request.GET.get("view")
    visible = SavedView.objects.filter(list_key=LIST_KEY).filter(
        Q(owner=request.user) | Q(shared=True)
    )
    saved = None
    if view_id and view_id.isdigit():
        saved = visible.filter(pk=view_id).first()
    elif not request.GET:
        saved = visible.filter(owner=request.user, is_default=True).first()
    if saved:
        return QueryDict(saved.filters.get("qs", "")), saved
    return request.GET, None


def build_page(
    request,
    *,
    base_url: str,
    fixed_client: Client | None = None,
    fixed_project: Project | None = None,
) -> dict:
    params, active_view = list_params(request)
    query, form = filters.parse(params)
    layout = query.layout
    queryset = filters.apply(
        dataclasses.replace(query, show_done=True) if layout == "board" else query,
        request.user,
        client=fixed_client,
    )
    if fixed_project is not None:
        queryset = queryset.filter(project=fixed_project)
    today = timezone.localdate()
    context = {}
    if layout == "board":
        mode = board_mod.valid_mode(query.by, project=fixed_project is not None)
        context["board"] = board_mod.build(queryset, mode, project=fixed_project, today=today)
        context["board_modes"] = [
            {
                "key": key,
                "label": label,
                "active": key == mode,
                "qs": filters.query_string(params, by="" if key == "status" else key),
            }
            for key, label in board_mod.MODES
            if key != "section" or fixed_project is not None
        ]
        context.update(
            total=1, groups=[], more=False, next_page=2, add_url_all=reverse("tasks:new")
        )
    elif layout == "calendar":
        anchor = calview.parse_anchor(params.get("date", ""), today)
        cal = query.cal if query.cal in calview.LAYOUT_KEYS else "month"
        on = query.on if query.on in calview.ON_KEYS else "target"
        data = calview.build(
            queryset, layout=cal, anchor=anchor, on=on, client=fixed_client, today=today
        )
        data["cal_anchor"] = anchor
        data["cal_links"] = {
            "prev": filters.query_string(params, date=data["cal_prev"].isoformat()),
            "next": filters.query_string(params, date=data["cal_next"].isoformat()),
            "today": filters.query_string(params, date=""),
            "month": filters.query_string(params, cal="", date=anchor.isoformat()),
            "week": filters.query_string(params, cal="week", date=anchor.isoformat()),
            "target": filters.query_string(params, on=""),
            "due": filters.query_string(params, on="due"),
        }
        context.update(data)
        context.update(
            total=1, groups=[], more=False, next_page=2, add_url_all=reverse("tasks:new")
        )
    else:
        try:
            page = min(max(int(params.get("page", 1)), 1), 50)
        except ValueError:
            page = 1
        result = listing.build(
            queryset,
            query,
            page=page,
            new_url=reverse("tasks:new"),
            client_id=fixed_client.pk if fixed_client else None,
            project_id=fixed_project.pk if fixed_project else None,
        )
        context.update(result)
        context["more_qs"] = filters.query_string(params, page=result["next_page"])

    effective = query.sort or filters.DEFAULT_SORT

    def sort_link(key):
        flipped = f"-{key}" if effective == key else key
        return filters.query_string(params, sort=flipped)

    columns = [
        ("name", "Task"),
        ("client", "Client"),
        ("category", "Category"),
        ("owner", "Owner"),
        (None, "Latest action"),
        ("status", "Status"),
        ("target", "Target"),
        ("deadline", "Deadline"),
    ]
    if fixed_client is not None:
        columns = [c for c in columns if c[0] != "client"]
    header = []
    for key, label in columns:
        header.append(
            {
                "label": label,
                "key": key,
                "qs": sort_link(key) if key else "",
                "sorted": "ascending"
                if effective == key
                else "descending"
                if effective == f"-{key}"
                else "",
            }
        )
    groups_options = [g for g in filters.GROUPS if g[0] != "section" or fixed_project is not None]
    return {
        "base_url": base_url,
        "fixed_client": fixed_client,
        "fixed_project": fixed_project,
        "form": form,
        "query": query,
        "layout": layout,
        "layouts": [
            {
                "key": key,
                "label": label,
                "active": key == layout,
                "qs": filters.query_string(params, layout="" if key == "table" else key),
            }
            for key, label in filters.LAYOUTS
        ],
        "chips": [
            {
                "key": key,
                "label": label,
                "active": query.chip == key,
                "qs": filters.query_string(params, chip="" if key == "all" else key),
            }
            for key, label in filters.CHIPS
        ],
        "show_done_qs": filters.query_string(params, show_done="" if query.show_done else "1"),
        "groups_options": groups_options,
        "state_inputs": [
            (k, params.get(k))
            for k in ("chip", "sort", "show_done", "layout", "by", "cal", "on", "date")
            if params.get(k)
        ],
        "header": header,
        "saved_views": SavedView.objects.filter(list_key=LIST_KEY)
        .filter(Q(owner=request.user) | Q(shared=True))
        .select_related("owner"),
        "active_view": active_view,
        "view_form": SavedViewForm(),
        "state_qs": filters.state_query(query, params),
        "current_qs": params.urlencode() if active_view is None else "",
        "today": today,
        "teams": list(Team.objects.all()),
        "user": request.user,
        "csrf_for_js": get_token(request),
        **context,
        **pick_lists(),
    }


# ------------------------------------------------------------------ the table


class TaskListView(StaffRequiredMixin, View):
    def get(self, request):
        context = build_page(request, base_url=reverse("tasks:list"))
        return respond(request, "tasks/task_list.html", "tasks/_page.html", context)


class ClientTasksView(ClientTabView):
    tab = "tasks"
    tab_template = "tasks/tabs/_tasks.html"

    def get(self, request, pk):
        if getattr(request, "htmx", False) and request.htmx.target == "task-page":
            client = get_client(pk)
            context = build_page(
                request, base_url=reverse("tasks:client_tasks", args=[pk]), fixed_client=client
            )
            return render(request, "tasks/_page.html", context)
        return super().get(request, pk)

    def context_tasks(self, request, client):
        context = build_page(
            request, base_url=reverse("tasks:client_tasks", args=[client.pk]), fixed_client=client
        )
        context.pop("user", None)
        return context


# ------------------------------------------------------------------ board and calendar moves


def _id(raw) -> int | None:
    raw = (raw or "").strip()
    return int(raw) if raw.isdigit() else None


def _plain(message: str, status: int = 422) -> HttpResponse:
    return HttpResponse(message, status=status, content_type="text/plain; charset=utf-8")


def column_target(by: str, key: str, task: Task):
    """The status, person, category, client or section a column key names."""
    if key == "none":
        value = None
    else:
        pk = _id(key)
        if pk is None:
            raise ValidationError("That column does not exist.")
        model = {
            "status": TaskStatus.objects.filter(active=True),
            "owner": User.objects.staff().filter(is_active=True),
            "category": TaskCategory.objects.filter(active=True),
            "client": Client.objects.all(),
            "section": ProjectSection.objects.all(),
        }.get(by)
        if model is None:
            raise ValidationError("That column cannot be changed by dragging.")
        value = model.filter(pk=pk).first()
        if value is None:
            raise ValidationError("That column does not exist.")
    return value


class BoardMoveView(StaffRequiredMixin, View):
    """Save a drag on the board: the card's new column and where it sits in it."""

    def post(self, request):
        task_id = _id(request.POST.get("task"))
        if task_id is None:
            return _plain("Choose a task.", 400)
        task = get_object_or_404(Task, pk=task_id)
        by = request.POST.get("by", "")
        try:
            value = column_target(by, request.POST.get("to", ""), task)
            lookup = {
                "status": "status",
                "owner": "owner",
                "category": "category",
                "client": "client",
                "section": "section",
            }[by]
            column = list(
                Task.objects.live().filter(**{lookup: value}).order_by(*board_mod.card_order())
            )
            by_id = {t.pk: t for t in column}
            before = by_id.get(_id(request.POST.get("before")) or 0)
            after = by_id.get(_id(request.POST.get("after")) or 0)
            services.move_task(
                request.user, task, by, value, column=column, before=before, after=after
            )
        except (ValidationError, KeyError) as exc:
            message = " ".join(exc.messages) if isinstance(exc, ValidationError) else "Cannot move."
            return _plain(message)
        card = board_mod.fetch_card(task.pk)
        return render(request, "tasks/_card.html", {"task": card})


class CalendarMoveView(StaffRequiredMixin, View):
    """Save a drag on the calendar. Only the target date changes."""

    def post(self, request):
        task_id = _id(request.POST.get("task"))
        if task_id is None:
            return _plain("Choose a task.", 400)
        task = get_object_or_404(Task, pk=task_id)
        try:
            day = _date(request.POST.get("date", ""))
            services.move_to_date(request.user, task, day)
        except ValidationError as exc:
            return _plain(" ".join(exc.messages))
        task = board_mod.fetch_card(task.pk)
        return render(request, "tasks/_cal_chip.html", {"task": task})


# ------------------------------------------------------------------ the drawer


def history_stream(task: Task) -> list[dict]:
    """Comments and the activity log in one stream, oldest first."""
    stream = [{"when": c.created_at, "comment": c} for c in task.comments.select_related("author")]
    content_type = ContentType.objects.get_for_model(Task)
    for event in (
        ActivityEvent.objects.filter(target_type=content_type, target_id=str(task.pk))
        .exclude(verb__in=["task.commented", "task.created"])
        .select_related("actor")
    ):
        stream.append({"when": event.created_at, "event": event})
    stream.sort(key=lambda item: item["when"])
    return stream


def drawer_context(request, task: Task, extra: dict | None = None) -> dict:
    today = timezone.localdate()
    listing.decorate([task], today)
    attachments = list(task.attachments.select_related("document"))
    for link in attachments:
        link.can_open = can_open_document(request.user, link.document)
    available = []
    if task.client_id:
        linked = {a.document_id for a in attachments}
        available = [
            d
            for d in task.client.documents.live()
            if d.pk not in linked and can_open_document(request.user, d)
        ][:100]
    context = {
        "task": task,
        "stream": history_stream(task),
        "comment_form": CommentForm(),
        "attachments": attachments,
        "available_documents": available,
        "followers": list(task.followers.all()),
        "is_following": task.followers.filter(pk=request.user.pk).exists(),
        "offer_complete": services.offer_to_complete(task),
        "kinds": TaskKind.choices,
        "priorities": Task.Priority.choices,
        "teams": list(Team.objects.all()),
        "total_steps": len(task.step_list),
        "done_steps": sum(1 for s in task.step_list if s.done_at),
        "today": today,
        "user": request.user,
        **pick_lists(),
    }
    context.update(extra or {})
    return context


class TaskDetailView(StaffRequiredMixin, View):
    def get(self, request, pk):
        task = get_task(request, pk)
        if wants_partial(request):
            return render(request, "tasks/_drawer.html", drawer_context(request, task))
        base = reverse("tasks:list")
        context = build_page(request, base_url=base)
        context["open_task"] = drawer_context(request, get_task(request, pk))
        return render(request, "tasks/task_list.html", context)


def drawer_response(request, task_pk, **extra):
    task = get_task(request, task_pk)
    return render(request, "tasks/_drawer.html", drawer_context(request, task, extra))


def respond_to_change(request, task_pk, error: str = ""):
    """After an edit: the drawer when it came from the drawer, otherwise the table row."""
    status = 422 if error else 200
    if request.POST.get("view") == "drawer":
        response = drawer_response(request, task_pk, form_error=error)
        response.status_code = status
        return response
    task = get_task(request, task_pk)
    return render(request, "tasks/_row.html", row_context(request, task, error), status=status)


def _date(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValidationError("Enter a date.") from error


def _lookup(model, raw, *, required=False, queryset=None):
    raw = (raw or "").strip()
    if not raw:
        if required:
            raise ValidationError("Choose a value.")
        return None
    if not raw.isdigit():
        raise ValidationError("Choose a value from the list.")
    found = (queryset if queryset is not None else model.objects.all()).filter(pk=int(raw)).first()
    if found is None:
        raise ValidationError("Choose a value from the list.")
    return found


def parse_field(field: str, raw: str):
    if field in ("owner", "reviewer"):
        return _lookup(User, raw, queryset=User.objects.staff().filter(is_active=True))
    if field == "status":
        return _lookup(
            TaskStatus, raw, required=True, queryset=TaskStatus.objects.filter(active=True)
        )
    if field == "category":
        return _lookup(TaskCategory, raw, queryset=TaskCategory.objects.filter(active=True))
    if field == "team":
        return _lookup(Team, raw)
    if field == "contact":
        return _lookup(Contact, raw)
    if field in ("target_date", "due_date", "start_date"):
        return _date(raw)
    if field == "estimate_minutes":
        raw = (raw or "").strip()
        if not raw:
            return None
        if not raw.isdigit():
            raise ValidationError("Enter a whole number of minutes.")
        return int(raw)
    return (raw or "").strip()


class TaskFieldView(StaffRequiredMixin, View):
    """Edit one field in place (the table) or in the drawer. Saves at once."""

    def post(self, request, pk, field):
        if field not in services.EDITABLE:
            raise Http404
        task = get_task(request, pk)
        error = ""
        try:
            value = parse_field(field, request.POST.get("value", ""))
            services.set_field(request.user, task, field, value)
        except ValidationError as exc:
            error = " ".join(exc.messages)
        return respond_to_change(request, pk, error)


class TaskActionView(StaffRequiredMixin, View):
    """Complete, cancel, star, follow."""

    action = ""

    def post(self, request, pk):
        task = get_task(request, pk)
        error = ""
        try:
            if self.action == "complete":
                services.complete(request.user, task)
            elif self.action == "cancel":
                services.cancel(request.user, task)
                messages.success(request, f"{task.title} was cancelled.")
                return done(request, reverse("tasks:list"))
            elif self.action == "star":
                services.toggle_star(request.user, task)
            elif self.action == "follow":
                services.toggle_follow(request.user, task)
        except ValidationError as exc:
            error = " ".join(exc.messages)
        return respond_to_change(request, pk, error)


class StepToggleView(StaffRequiredMixin, View):
    def post(self, request, pk, step_pk):
        task = get_task(request, pk)
        step = get_object_or_404(task.steps, pk=step_pk)
        error = ""
        try:
            services.toggle_step(request.user, step)
        except ValidationError as exc:
            error = " ".join(exc.messages)
        return respond_to_change(request, pk, error)


class StepPickView(StaffRequiredMixin, View):
    """The Latest action drop-down in a row: choosing a step ticks it."""

    def post(self, request, pk):
        task = get_task(request, pk)
        raw = request.POST.get("step", "")
        error = ""
        try:
            step = _lookup(None, raw, queryset=task.steps.all())
            if step is not None and not step.is_done:
                services.toggle_step(request.user, step, done=True)
        except ValidationError as exc:
            error = " ".join(exc.messages)
        return respond_to_change(request, pk, error)


class CommentView(StaffRequiredMixin, View):
    def post(self, request, pk):
        task = get_task(request, pk)
        form = CommentForm(request.POST)
        error = ""
        if not form.is_valid():
            error = "Write a comment first."
        else:
            try:
                services.add_comment(request.user, task, form.cleaned_data["body"])
            except ValidationError as exc:
                error = " ".join(exc.messages)
        return respond_to_change(request, pk, error)


class DescriptionView(StaffRequiredMixin, View):
    def get(self, request, pk):
        task = get_task(request, pk)
        return render(request, "tasks/_description_form.html", {"task": task})

    def post(self, request, pk):
        task = get_task(request, pk)
        services.set_description(request.user, task, request.POST.get("description", ""))
        return respond_to_change(request, pk)


class AttachView(StaffRequiredMixin, View):
    """Upload a file, or attach one the client already has. Plain form posts, then back."""

    def post(self, request, pk):
        task = get_task(request, pk)
        try:
            upload = request.FILES.get("file")
            document_id = request.POST.get("document", "")
            if upload:
                services.attach_upload(request.user, task, upload)
                messages.success(request, "File attached.")
            elif document_id.isdigit():
                document = get_object_or_404(Document.objects.live(), pk=int(document_id))
                if not can_open_document(request.user, document):
                    raise PermissionDenied
                services.attach_document(request.user, task, document)
                messages.success(request, "Document attached.")
            else:
                messages.error(request, "Choose a file or a document.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect("tasks:detail", pk=pk)


# ------------------------------------------------------------------ new task, bulk


def prefill_from(request) -> dict:
    initial = {"owner": request.user.pk}
    for key in (
        "client",
        "owner",
        "status",
        "category",
        "service",
        "kind",
        "target_date",
        "project",
        "section",
    ):
        value = request.GET.get(key)
        if value is None:
            continue
        if key == "client" and value.isdigit():
            client = Client.objects.filter(pk=int(value)).first()
            if client:
                initial["client_text"] = client_label(client)
        elif key == "owner" and value == "":
            initial["owner"] = ""
        else:
            initial[key] = value
    return initial


class TaskCreateView(StaffRequiredMixin, View):
    def _render(self, request, form, status=200):
        return render_form(
            request,
            title="New task",
            form=form,
            action=reverse("tasks:new"),
            target="drawer",
            submit="Create task",
            status=status,
            extra="tasks/_new_task_extra.html",
            back=reverse("tasks:list"),
        )

    def get(self, request):
        return self._render(request, TaskCreateForm(initial=prefill_from(request)))

    def post(self, request):
        form = TaskCreateForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, 422)
        data = form.cleaned_data
        try:
            task = services.create_task(
                request.user,
                title=data["title"],
                client=data["client_text"],
                kind=data["kind"],
                category=data["category"],
                owner=data["owner"],
                status=data["status"],
                target_date=data["target_date"],
                due_date=data["due_date"],
                description=data["description"],
                service=data["service"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self._render(request, form, 422)
        return done(request, reverse("tasks:detail", args=[task.pk]), "Task created.")


class ClientOptionsView(StaffRequiredMixin, View):
    """Options for the client box's list while typing."""

    def get(self, request):
        from apps.clients.services import search_clients

        text = request.GET.get("client_text", request.GET.get("q", "")).strip()
        clients = list(search_clients(text)[:15]) if len(text) >= 2 else []
        return render(
            request, "tasks/_client_options.html", {"clients": clients, "label": client_label}
        )


class BulkView(StaffRequiredMixin, View):
    def post(self, request):
        ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
        back = request.POST.get("next", "")
        if not back.startswith("/") or back.startswith("//"):
            back = reverse("tasks:list")
        if not ids:
            messages.error(request, "Tick at least one task first.")
            return redirect(back)
        action = request.POST.get("action", "")
        try:
            value = None
            if action == "owner":
                value = parse_field("owner", request.POST.get("owner", ""))
            elif action == "status":
                value = parse_field("status", request.POST.get("status", ""))
            elif action == "target_date":
                value = parse_field("target_date", request.POST.get("target_date", ""))
            tasks = list(Task.objects.live().filter(pk__in=ids).select_related("client", "status"))
            changed = services.bulk(request.user, tasks, action, value)
            messages.success(request, f"{changed} task{'s' if changed != 1 else ''} updated.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect(back)


# ------------------------------------------------------------------ saved views


class SavedViewCreateView(StaffRequiredMixin, View):
    def post(self, request):
        form = SavedViewForm(request.POST)
        back = reverse("tasks:list")
        if not form.is_valid():
            messages.error(request, "Give the view a name.")
            return redirect(back)
        source = QueryDict(request.POST.get("query", ""))
        query, _ = filters.parse(source)
        saved = form.save(commit=False)
        saved.owner = request.user
        saved.list_key = LIST_KEY
        saved.filters = {"qs": filters.state_query(query, source)}
        saved.save()
        events.record(
            request.user,
            "view.saved",
            f"{request.user} saved the task view “{saved.name}”"
            f"{' for everyone' if saved.shared else ''}.",
            view_id=saved.pk,
        )
        messages.success(request, f"View “{saved.name}” saved.")
        return redirect(f"{back}?view={saved.pk}")


class SavedViewDefaultView(StaffRequiredMixin, View):
    """Make a view the one that opens first. Only your own; the same again clears it."""

    def post(self, request, pk):
        saved = get_object_or_404(
            SavedView.objects.filter(Q(owner=request.user) | Q(shared=True)),
            pk=pk,
            list_key=LIST_KEY,
        )
        mine = SavedView.objects.filter(owner=request.user, list_key=LIST_KEY)
        was = mine.filter(pk=saved.pk, is_default=True).exists()
        mine.update(is_default=False)
        if saved.owner_id == request.user.pk and not was:
            mine.filter(pk=saved.pk).update(is_default=True)
            messages.success(request, f"“{saved.name}” now opens first.")
        elif saved.owner_id != request.user.pk:
            # A shared view you do not own: keep your own copy as the default.
            copy = SavedView.objects.create(
                list_key=LIST_KEY,
                name=f"{saved.name} (mine)"[:80],
                owner=request.user,
                filters=saved.filters,
                is_default=True,
            )
            messages.success(request, f"Saved your own copy, “{copy.name}”, to open first.")
        else:
            messages.success(request, "No view opens first now.")
        return redirect("tasks:list")


class SavedViewDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        saved = get_object_or_404(SavedView, pk=pk, list_key=LIST_KEY)
        if saved.owner_id != request.user.pk and not request.user.is_owner:
            raise PermissionDenied
        name = saved.name
        saved.delete()
        events.record(request.user, "view.deleted", f"{request.user} deleted the view “{name}”.")
        messages.success(request, f"View “{name}” deleted.")
        return redirect("tasks:list")


# ------------------------------------------------------------------ My work

SECTIONS = [
    ("overdue", "Overdue"),
    ("today", "Today"),
    ("week", "This week"),
    ("later", "Later"),
    ("waiting", "Waiting on client"),
]


def my_sections(user, today: date | None = None) -> list[dict]:
    """The user's open tasks in sections. A task sits by its target date, else its deadline."""
    today = today or timezone.localdate()
    _, end_of_week = filters.week_bounds(today)
    tasks = (
        Task.objects.open()
        .filter(owner=user)
        .select_related("client", "status", "owner", "category")
        .prefetch_related("steps")
        .annotate(is_starred=Exists(TaskStar.objects.filter(task=OuterRef("pk"), user=user)))
        .order_by("target_date", "due_date", "id")
    )
    buckets = {key: [] for key, _ in SECTIONS}
    for task in tasks:
        when = task.target_date or task.due_date
        if task.status.is_waiting:
            key = "waiting"
        elif when and when < today:
            key = "overdue"
        elif when == today:
            key = "today"
        elif when and when <= end_of_week:
            key = "week"
        else:
            key = "later"
        buckets[key].append(task)
    return [
        {"key": key, "label": label, "tasks": listing.decorate(buckets[key], today)}
        for key, label in SECTIONS
    ]


class MyWorkView(StaffRequiredMixin, View):
    """The staff home page until Stage 8 builds the Overview."""

    def get(self, request):
        context = {
            "sections": my_sections(request.user),
            "unassigned_count": Task.objects.open().filter(owner__isnull=True).count(),
            "today": timezone.localdate(),
            "row_error": "",
            "header": [
                {"label": label, "key": None}
                for label in (
                    "Task",
                    "Client",
                    "Category",
                    "Owner",
                    "Latest action",
                    "Status",
                    "Target",
                    "Deadline",
                )
            ],
            **pick_lists(),
        }
        from apps.onboarding.panels import overview_context

        context.update(overview_context(request.user))
        return render(request, "tasks/my_work.html", context)
