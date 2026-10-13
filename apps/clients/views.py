import csv
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from apps import events
from apps.core.pagination import paginate
from apps.core.permissions import CapabilityRequiredMixin, StaffRequiredMixin
from apps.events.models import ActivityEvent

from . import columns as cols
from . import panels, services
from .forms import (
    CallForm,
    ClientCreateForm,
    ClientFilterForm,
    DeleteForm,
    NoteForm,
    ReasonForm,
    SavedViewForm,
    StatusForm,
    panel_form_class,
)
from .models import Client, Note, SavedView
from .views_base import done, get_client, render_form, respond

FILTER_KEYS = ("q", "status", "client_type", "manager", "partner", "team", "tag", "archived")


# ------------------------------------------------------------------ list


def _list_params(request) -> tuple[QueryDict, SavedView | None]:
    """The query to use: the request's own, or a saved view's."""
    view_id = request.GET.get("view")
    if view_id and view_id.isdigit():
        saved = (
            SavedView.objects.filter(pk=view_id, list_key="clients")
            .filter(Q(owner=request.user) | Q(shared=True))
            .first()
        )
        if saved:
            params = QueryDict(mutable=True)
            for key, value in saved.filters.items():
                params.setlist(key, value if isinstance(value, list) else [value])
            params.setlist("cols", saved.columns)
            if saved.sort:
                params["sort"] = saved.sort
            return params, saved
    return request.GET, None


def filtered_clients(form: ClientFilterForm):
    queryset = Client.objects.select_related("manager", "partner", "team").prefetch_related("tags")
    data = form.cleaned_data if form.is_valid() else {}
    only_archived = data.get("archived") == "only"
    queryset = queryset.archived() if only_archived else queryset.not_archived()
    queryset = queryset.filter(status__in=form.chosen_statuses())
    if data.get("q"):
        queryset = queryset.filter(pk__in=services.search_clients(data["q"]).values("pk"))
    for field, lookup in (
        ("client_type", "client_type"),
        ("manager", "manager"),
        ("partner", "partner"),
        ("team", "team"),
        ("tag", "tags"),
    ):
        if data.get(field):
            queryset = queryset.filter(**{lookup: data[field]})
    return queryset.distinct()


class ClientListView(StaffRequiredMixin, View):
    def get(self, request):
        params, active_view = _list_params(request)
        form = ClientFilterForm(params)
        chosen_columns = cols.clean_columns(params.getlist("cols") or cols.DEFAULT_COLUMNS)
        sort = cols.valid_sort(params.get("sort", ""))
        queryset = filtered_clients(form).order_by(*cols.ordering_for(sort))
        page = paginate(request, queryset, per_page=50)
        keep = params.copy()
        keep.pop("page", None)
        keep.pop("view", None)
        keep.pop("sort", None)
        context = {
            "form": form,
            "page": page,
            "columns": [(k, cols.COLUMNS[k][0]) for k in chosen_columns],
            "all_columns": [(k, v[0], k in chosen_columns) for k, v in cols.COLUMNS.items()],
            "sort": sort,
            "keep_query": keep.urlencode(),
            "export_query": _export_query(form, chosen_columns, sort),
            "saved_views": SavedView.objects.filter(list_key="clients")
            .filter(Q(owner=request.user) | Q(shared=True))
            .select_related("owner"),
            "active_view": active_view,
            "view_form": SavedViewForm(),
            "statuses": Client.Status.choices,
            "chosen_statuses": form.chosen_statuses(),
        }
        return render(request, "clients/client_list.html", context)


def _export_query(form, chosen_columns, sort) -> str:
    pairs = [("cols", c) for c in chosen_columns]
    if sort:
        pairs.append(("sort", sort))
    for key in FILTER_KEYS:
        raw = form.data.getlist(key) if hasattr(form.data, "getlist") else []
        pairs += [(key, v) for v in raw if v]
    return urlencode(pairs)


class ClientExportView(CapabilityRequiredMixin, View):
    required_rights = ("data.export",)
    require_reauth = True
    reauth_allow_get = False  # a download is a GET, so the password is asked for on GET too

    def get(self, request):
        params = request.GET
        form = ClientFilterForm(params)
        keys = cols.clean_columns(params.getlist("cols") or cols.DEFAULT_COLUMNS)
        queryset = filtered_clients(form).order_by(
            *cols.ordering_for(cols.valid_sort(params.get("sort", "")))
        )
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="clients.csv"'
        response["Cache-Control"] = "no-store"
        writer = csv.writer(response)
        writer.writerow([cols.COLUMNS[k][0] for k in keys])
        count = 0
        for client in queryset:
            writer.writerow([_safe_cell(v) for v in cols.csv_row(client, keys)])
            count += 1
        events.record(
            request.user,
            "export.run",
            f"{request.user} exported {count} clients to CSV.",
            rows=count,
            columns=keys,
            list="clients",
        )
        return response


def _safe_cell(value: str) -> str:
    """Stop a spreadsheet treating text as a formula."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


class SavedViewCreateView(StaffRequiredMixin, View):
    def post(self, request):
        form = SavedViewForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Give the view a name.")
            return redirect("clients:list")
        source = QueryDict(request.POST.get("query", ""))
        filters = {k: source.getlist(k) for k in FILTER_KEYS if source.getlist(k)}
        saved = form.save(commit=False)
        saved.owner = request.user
        saved.filters = filters
        saved.columns = cols.clean_columns(source.getlist("cols") or cols.DEFAULT_COLUMNS)
        saved.sort = cols.valid_sort(source.get("sort", ""))
        saved.save()
        events.record(
            request.user,
            "view.saved",
            f"{request.user} saved the client list view “{saved.name}”"
            f"{' for everyone' if saved.shared else ''}.",
            view_id=saved.pk,
        )
        messages.success(request, f"View “{saved.name}” saved.")
        return redirect(f"{reverse('clients:list')}?view={saved.pk}")


class SavedViewDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        saved = get_object_or_404(SavedView, pk=pk, list_key="clients")
        if saved.owner_id != request.user.pk and not request.user.is_owner:
            raise PermissionDenied
        name = saved.name
        saved.delete()
        events.record(request.user, "view.deleted", f"{request.user} deleted the view “{name}”.")
        messages.success(request, f"View “{name}” deleted.")
        return redirect("clients:list")


# ------------------------------------------------------------------ search


class SearchDropdownView(StaffRequiredMixin, View):
    def get(self, request):
        query = request.GET.get("q", "").strip()
        results = []
        if len(query) >= 2:
            results = list(services.search_clients(query)[:8])
        return render(request, "clients/_search_dropdown.html", {"results": results, "q": query})


class SearchResultsView(StaffRequiredMixin, View):
    def get(self, request):
        query = request.GET.get("q", "").strip()
        clients = (
            services.search_clients(query, include_archived=True).prefetch_related("tags")
            if query
            else Client.objects.none()
        )
        people = services.search_contacts(query)[:20] if query else []
        context = {
            "q": query,
            "page": paginate(request, clients, per_page=50),
            "people": people,
        }
        return render(request, "clients/search_results.html", context)


# ------------------------------------------------------------------ new client


class ClientCreateView(StaffRequiredMixin, View):
    def get(self, request):
        return render(request, "clients/client_new.html", {"form": ClientCreateForm()})

    def post(self, request):
        form = ClientCreateForm(request.POST)
        if not form.is_valid():
            return render(request, "clients/client_new.html", {"form": form}, status=422)
        data = form.cleaned_data
        contact = None
        if data["first_name"]:
            existing = services.find_matching_contacts(
                email=data["email"], first_name=data["first_name"], last_name=data["last_name"]
            ).first()
            contact = existing or services.create_contact(
                request.user,
                first_name=data["first_name"],
                last_name=data["last_name"],
                email=data["email"],
            )
            if existing:
                messages.info(
                    request, f"{existing.full_name} is already on file, so that person was linked."
                )
        client = services.create_client(
            request.user,
            name=data["name"],
            client_type=data["client_type"],
            manager=data["manager"],
            contact=contact,
        )
        return done(
            request, reverse("clients:detail", args=[client.pk]), f"{client.name} was added."
        )


# ------------------------------------------------------------------ client page

TABS = [
    ("info", "Info", "clients:detail"),
    ("timeline", "Timeline", "clients:timeline"),
    ("contacts", "Contacts", "clients:contacts"),
    ("links", "Links", "clients:links"),
    ("documents", "Documents", "clients:documents"),
]


def tab_nav(client: Client) -> list[tuple[str, str, str]]:
    return [(label, reverse(name, args=[client.pk]), key) for key, label, name in TABS]


class ClientTabView(StaffRequiredMixin, View):
    """One tab of the client page. Each tab has its own address and loads with HTMX."""

    tab = "info"

    def get(self, request, pk):
        client = get_client(pk)
        context = {
            "client": client,
            "tab": self.tab,
            "tabs": tab_nav(client),
            "tab_template": f"clients/tabs/_{self.tab}.html",
            "no_main_contact": not client.client_contacts.filter(is_main=True).exists(),
        }
        context.update(getattr(self, f"context_{self.tab}")(request, client))
        return respond(request, "clients/client_page.html", "clients/_body.html", context)

    def context_info(self, request, client):
        pinned = client.notes.filter(pinned=True, kind=Note.Kind.NOTE).select_related("author")
        shown = []
        for panel in panels.visible_panels(client):
            shown.append(panel_context(request, client, panel.key))
        return {"pinned_notes": pinned, "panels": shown}

    def context_timeline(self, request, client):
        queryset = ActivityEvent.objects.filter(client=client).select_related("actor")
        kind = request.GET.get("type", "")
        if kind:
            queryset = queryset.filter(verb__startswith=f"{kind}.")
        prefixes = sorted(
            {
                v.split(".")[0]
                for v in ActivityEvent.objects.filter(client=client)
                .values_list("verb", flat=True)
                .distinct()
            }
        )
        page = paginate(request, queryset, per_page=50)
        note_ids = [e.data.get("note_id") for e in page.object_list if e.data.get("note_id")]
        notes = {n.pk: n for n in Note.objects.filter(pk__in=note_ids)}
        for event in page.object_list:
            event.note = notes.get(event.data.get("note_id"))
        return {"page": page, "type": kind, "type_choices": prefixes}

    def context_contacts(self, request, client):
        links = client.client_contacts.select_related("contact")
        return {"links": links}

    def context_links(self, request, client):
        return {"linked": services.linked_clients(client)}

    def context_documents(self, request, client):
        from . import views_documents

        return views_documents.documents_context(request, client)


class ClientDetailView(ClientTabView):
    tab = "info"


class ClientTimelineView(ClientTabView):
    tab = "timeline"


class ClientContactsView(ClientTabView):
    tab = "contacts"


class ClientLinksView(ClientTabView):
    tab = "links"


class ClientDocumentsView(ClientTabView):
    tab = "documents"


# ------------------------------------------------------------------ panels


def panel_context(request, client, key: str, form=None) -> dict:
    panel = panels.PANELS.get(key)
    if panel is None or panel not in panels.visible_panels(client):
        raise Http404
    context = {
        "client": client,
        "panel": panel,
        "rows": panels.rows_for(client, key, request.user),
        "form": form,
    }
    if key == "main_contact":
        context["main_contact"] = client.main_contact
        context["has_individual_client"] = bool(
            context["main_contact"]
            and Client.objects.filter(
                client_type=Client.Type.INDIVIDUAL,
                client_contacts__contact=context["main_contact"],
                client_contacts__is_main=True,
            ).exists()
        )
    return context


class PanelView(StaffRequiredMixin, View):
    def get(self, request, pk, key):
        client = get_client(pk)
        return render(request, "clients/_panel.html", panel_context(request, client, key))


class PanelEditView(StaffRequiredMixin, View):
    def _form(self, client, key, data=None):
        panel = panels.PANELS.get(key)
        if panel is None or not panel.editable or panel not in panels.visible_panels(client):
            raise Http404
        return panel_form_class(key, client)(data, instance=client)

    def get(self, request, pk, key):
        client = get_client(pk)
        form = self._form(client, key)
        return render(request, "clients/_panel.html", panel_context(request, client, key, form))

    def post(self, request, pk, key):
        client = get_client(pk)
        form = self._form(client, key, request.POST)
        if not form.is_valid():
            return render(
                request,
                "clients/_panel.html",
                panel_context(request, client, key, form),
                status=422,
            )
        services.update_client(request.user, client, form, section=panels.PANELS[key].title)
        client.refresh_from_db()
        return render(request, "clients/_panel.html", panel_context(request, client, key))


class ClientRevealView(StaffRequiredMixin, View):
    """Show one encrypted value. A POST, and always logged."""

    def post(self, request, pk, field):
        client = get_client(pk)
        value = services.reveal_value(request.user, client, field)
        response = render(
            request,
            "clients/_revealed.html",
            {"value": value, "name": field, "kind": "client", "owner_id": client.pk},
        )
        response["Cache-Control"] = "no-store"
        return response


# ------------------------------------------------------------------ status, archive, delete


class ClientActionMixin(StaffRequiredMixin):
    right: str | None = None

    def has_access(self, request) -> bool:
        return self.right is None or request.user.can(self.right)


class ChangeStatusView(ClientActionMixin, View):
    right = "clients.status"

    def get(self, request, pk):
        client = get_client(pk)
        return self._render(request, client, StatusForm(client=client, initial={}))

    def _render(self, request, client, form, status=200):
        return render_form(
            request,
            title=f"Change status of {client.name}",
            form=form,
            action=reverse("clients:status", args=[client.pk]),
            submit="Change status",
            status=status,
            intro=f"Currently {client.get_status_display().lower()}. Later stages add the proper "
            "routes (onboarding and proposals); until then a manager can change it by hand.",
        )

    def post(self, request, pk):
        client = get_client(pk)
        form = StatusForm(request.POST, client=client)
        if not form.is_valid():
            return self._render(request, client, form, 422)
        data = form.cleaned_data
        try:
            services.change_status(
                request.user,
                client,
                data["status"],
                ended_on=data["ended_on"],
                reason=data["reason"],
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, client, form, 422)
        return done(request, reverse("clients:detail", args=[client.pk]), "Status changed.")


class ArchiveView(ClientActionMixin, View):
    right = "clients.archive"

    def _render(self, request, client, form, status=200):
        return render_form(
            request,
            title=f"Archive {client.name}",
            form=form,
            action=reverse("clients:archive", args=[client.pk]),
            submit="Archive client",
            status=status,
            intro="An archived client is hidden from lists and search. Nothing is deleted.",
        )

    def get(self, request, pk):
        return self._render(request, get_client(pk), ReasonForm())

    def post(self, request, pk):
        client = get_client(pk)
        form = ReasonForm(request.POST)
        if not form.is_valid():
            return self._render(request, client, form, 422)
        services.archive_client(request.user, client, form.cleaned_data["reason"])
        return done(request, reverse("clients:list"), f"{client.name} was archived.")


class RestoreView(ClientActionMixin, View):
    right = "clients.archive"

    def post(self, request, pk):
        client = get_client(pk)
        services.restore_client(request.user, client)
        return done(
            request, reverse("clients:detail", args=[client.pk]), f"{client.name} was restored."
        )


class DeleteView(ClientActionMixin, View):
    right = "clients.delete"

    def _render(self, request, client, form, status=200):
        block = services.delete_block(client)
        return render_form(
            request,
            title=f"Delete {client.name} for good",
            form=form,
            action=reverse("clients:delete", args=[client.pk]),
            submit="Delete for good",
            status=status,
            danger=True,
            intro=block
            or "This removes the client, its links, notes and documents. People stay on file. "
            "It cannot be undone, and it is recorded in the audit log.",
        )

    def get(self, request, pk):
        return self._render(request, get_client(pk), DeleteForm())

    def post(self, request, pk):
        client = get_client(pk)
        form = DeleteForm(request.POST)
        if not form.is_valid():
            return self._render(request, client, form, 422)
        try:
            services.delete_client(request.user, client, form.cleaned_data["confirm_name"])
        except ValidationError as error:
            form.add_error("confirm_name" if "Type" in str(error) else None, error)
            return self._render(request, client, form, 422)
        return done(request, reverse("clients:list"), "The client was deleted for good.")


# ------------------------------------------------------------------ notes


class AddNoteView(StaffRequiredMixin, View):
    kind = Note.Kind.NOTE

    def _render(self, request, client, form, status=200):
        call = self.kind == Note.Kind.CALL
        return render_form(
            request,
            title=("Log a call with " if call else "Add a note to ") + client.name,
            form=form,
            action=reverse("clients:log_call" if call else "clients:add_note", args=[client.pk]),
            submit="Log call" if call else "Add note",
            target="drawer",
            status=status,
        )

    def get(self, request, pk):
        client = get_client(pk)
        return self._render(
            request, client, CallForm() if self.kind == Note.Kind.CALL else NoteForm()
        )

    def post(self, request, pk):
        client = get_client(pk)
        form = (CallForm if self.kind == Note.Kind.CALL else NoteForm)(request.POST)
        if not form.is_valid():
            return self._render(request, client, form, 422)
        services.add_note(
            request.user,
            client,
            form.cleaned_data["text"],
            kind=self.kind,
            pinned=form.cleaned_data.get("pinned", False),
        )
        return done(request, reverse("clients:timeline", args=[client.pk]))


class LogCallView(AddNoteView):
    kind = Note.Kind.CALL


class PinNoteView(StaffRequiredMixin, View):
    def post(self, request, pk, note_pk):
        client = get_client(pk)
        note = get_object_or_404(Note, pk=note_pk, client=client)
        services.toggle_pin(request.user, note)
        target = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
            target = reverse("clients:detail", args=[client.pk])
        return done(request, target)
