"""Who can reach what. A new address that is not listed here fails the completeness tests."""

import uuid

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import sign_in, staff
from apps.clients.tests.factories import ClientFactory, DocumentFactory
from apps.portal import requests as request_services
from apps.portal.models import PortalForm, PortalItem, Request
from apps.portal.tests.helpers import portal_person
from apps.portal.urls import urlpatterns

pytestmark = pytest.mark.django_db

PORTAL_ONLY = {
    "home", "switch", "documents", "upload", "document", "requests", "request_new",
    "request_detail", "details", "item", "item_upload", "item_everything", "item_approve",
    "form", "logout",
}  # fmt: skip
SIGN_IN_PAGES = {"login", "login_code"}
PUBLIC = {"request_form", "request_thanks"}


@pytest.fixture
def world():
    a, b = ClientFactory(name="Alpha Ltd"), ClientFactory(name="Bravo Ltd")
    user_a, contact_a, _ = portal_person(a)
    user_b, contact_b, _ = portal_person(b)
    doc = DocumentFactory(client=a, shared_with_portal=True, title="Alpha shared")
    secret = DocumentFactory(client=a, shared_with_portal=False, title="Alpha staff only")
    upload = PortalItem.objects.create(
        client=a, kind=PortalItem.Kind.UPLOAD_RECORDS, title="Upload for Alpha"
    )
    approve = PortalItem.objects.create(
        client=a,
        kind=PortalItem.Kind.APPROVE_DOCUMENT,
        title="Approve for Alpha",
        object_id=doc.pk,
    )
    confirm = PortalItem.objects.create(
        client=a, kind=PortalItem.Kind.CONFIRM_DETAILS, title="Confirm Alpha"
    )
    form = PortalForm.objects.create(item=confirm, client=a, kind=PortalForm.Kind.CONFIRMATION)
    req = Request.objects.create(
        client=a,
        contact=contact_a,
        channel=Request.Channel.PORTAL,
        subject="Alpha question",
        body="x",
    )
    return {
        "a": a, "b": b, "user_a": user_a, "user_b": user_b, "doc": doc, "secret": secret,
        "upload": upload, "approve": approve, "confirm": confirm, "form": form, "req": req,
    }  # fmt: skip


def object_addresses(w):
    """Every portal address that names an object, with the object of client A."""
    return [
        ("document", [w["doc"].public_id]),
        ("document", [w["secret"].public_id]),
        ("request_detail", [w["req"].public_id]),
        ("item", [w["upload"].public_id]),
        ("item_upload", [w["upload"].public_id]),
        ("item_everything", [w["upload"].public_id]),
        ("item_approve", [w["approve"].public_id]),
        ("form", [w["confirm"].public_id]),
    ]


def test_every_portal_address_is_covered(world):
    """A new portal or public address must be added to the lists in this file."""
    names = {p.name for p in urlpatterns if str(p.pattern).startswith(("portal/", "r/"))}
    covered = PORTAL_ONLY | SIGN_IN_PAGES | PUBLIC
    assert names == covered, f"Not covered: {names - covered}; stale: {covered - names}"
    object_names = {n for n, _ in object_addresses(world)}
    assert {"document", "request_detail", "item", "item_upload", "item_everything"} <= object_names


def test_a_user_of_another_client_gets_404_for_every_object(client, world):
    client.force_login(world["user_b"])
    for name, args in object_addresses(world):
        url = reverse(f"portal:{name}", args=args)
        codes = [client.get(url).status_code, client.post(url).status_code]
        # A method the view does not offer is 405 whoever asks. The other must be 404.
        assert set(codes) <= {404, 405} and 404 in codes, (name, codes)


def test_the_same_objects_work_for_the_right_client(client, world):
    client.force_login(world["user_a"])
    for name in ("item", "request_detail", "form"):
        args = {"item": "upload", "request_detail": "req", "form": "confirm"}[name]
        key = world[args].public_id
        assert client.get(reverse(f"portal:{name}", args=[key])).status_code == 200
    assert client.get(reverse("portal:document", args=[world["doc"].public_id])).status_code == 200


def test_staff_only_documents_are_never_served_to_the_portal(client, world):
    client.force_login(world["user_a"])
    assert (
        client.get(reverse("portal:document", args=[world["secret"].public_id])).status_code == 404
    )


def test_unknown_uuids_are_404(client, world):
    client.force_login(world["user_a"])
    for name in ("document", "request_detail", "item", "form"):
        assert client.get(reverse(f"portal:{name}", args=[uuid.uuid4()])).status_code == 404


def test_list_pages_show_only_the_signed_in_clients_data(client, world):
    client.force_login(world["user_b"])
    for name in ("home", "documents", "requests", "details"):
        text = client.get(reverse(f"portal:{name}")).content.decode()
        for leak in ("Alpha shared", "Alpha question", "Upload for Alpha", "Alpha Ltd"):
            assert leak not in text, (name, leak)


def test_signed_out_portal_addresses_redirect_to_the_portal_sign_in(client, world):
    for name in PORTAL_ONLY - {"logout"}:
        args = [world["upload"].public_id] if name.startswith(("item", "form")) else []
        if name in ("document", "request_detail"):
            args = [uuid.uuid4()]
        response = client.get(reverse(f"portal:{name}", args=args))
        assert response.status_code == 302, name
        assert response.url.startswith(reverse("portal:login")), name


def test_a_staff_account_gets_403_on_portal_pages(client, world):
    sign_in(client, staff())
    for name in ("home", "documents", "requests", "details", "upload", "switch"):
        assert client.get(reverse(f"portal:{name}")).status_code == 403, name
    assert client.get(reverse("portal:item", args=[world["upload"].public_id])).status_code == 403


def test_a_withdrawn_contact_sees_nothing(client, world):
    from apps.clients.models import ClientContact

    ClientContact.objects.filter(contact__portal_user=world["user_a"]).update(portal_access=False)
    client.force_login(world["user_a"])
    assert client.get(reverse("portal:home")).status_code == 404
    assert client.get(reverse("portal:item", args=[world["upload"].public_id])).status_code == 404


def test_a_contact_who_resigned_sees_nothing(client, world):
    import datetime

    from apps.clients.models import ClientContact

    ClientContact.objects.filter(contact__portal_user=world["user_a"]).update(
        resigned_on=datetime.date(2020, 1, 1)
    )
    client.force_login(world["user_a"])
    assert client.get(reverse("portal:home")).status_code == 404


def test_the_switcher_only_offers_your_own_clients(client, world):
    from apps.clients.models import ClientContact

    third = ClientFactory(name="Charlie Ltd")
    ClientContact.objects.create(
        client=third, contact=world["user_a"].portal_contact, portal_access=True
    )
    client.force_login(world["user_a"])
    page = client.get(reverse("portal:home")).content.decode()
    assert "Alpha Ltd" in page and "Charlie Ltd" in page and "Bravo Ltd" not in page
    response = client.post(reverse("portal:switch"), {"client": str(world["b"].public_id)})
    assert response.status_code == 404
    response = client.post(reverse("portal:switch"), {"client": str(third.public_id)})
    assert response.status_code == 302
    assert "Charlie Ltd" in client.get(reverse("portal:home")).content.decode()


def test_an_item_for_another_business_of_the_same_person_switches_to_it(client, world):
    from apps.clients.models import ClientContact

    third = ClientFactory(name="Charlie Ltd")
    ClientContact.objects.create(
        client=third, contact=world["user_a"].portal_contact, portal_access=True
    )
    other = PortalItem.objects.create(
        client=third, kind=PortalItem.Kind.UPLOAD_RECORDS, title="Charlie upload"
    )
    client.force_login(world["user_a"])
    response = client.get(reverse("portal:item", args=[other.public_id]), follow=True)
    assert response.status_code == 200 and "Charlie upload" in response.content.decode()


def test_an_item_for_a_named_contact_is_hidden_from_a_colleague(client, world):
    colleague, contact2, _ = portal_person(world["a"], main=False)
    private = PortalItem.objects.create(
        client=world["a"],
        contact=world["user_a"].portal_contact,
        kind=PortalItem.Kind.UPLOAD_RECORDS,
        title="Only for the first person",
    )
    client.force_login(colleague)
    assert client.get(reverse("portal:item", args=[private.public_id])).status_code == 404
    assert "Only for the first person" not in client.get(reverse("portal:home")).content.decode()
    del contact2


# ---------------------------------------------------------------- the request link


def test_the_request_link_rejects_wrong_tokens(client, world):
    for token in ("nope", "x" * 200, world["a"].request_token or "empty"):
        assert client.get(reverse("portal:request_form", args=[token])).status_code == 404
        assert client.get(reverse("portal:request_thanks", args=[token])).status_code == 404


def test_the_request_link_shows_only_the_clients_name(client, world):
    token = request_services.ensure_token(world["a"])
    page = client.get(reverse("portal:request_form", args=[token])).content.decode()
    assert "Alpha Ltd" in page
    assert "Bravo Ltd" not in page


# ---------------------------------------------------------------- staff addresses


STAFF_NAMES_GET = [
    "inbox", "inbox_log", "inbox_detail", "inbox_convert", "inbox_link", "inbox_reply",
    "inbox_close", "inbox_client", "client_requests", "task_ask_approve", "review",
]  # fmt: skip
STAFF_NAMES_POST = [
    "inbox_spam", "inbox_reopen", "replace_link", "invite", "withdraw", "item_cancel",
    "task_ask_upload", "review_act",
]  # fmt: skip
STAFF_NAMES_OTHER = {"inbox_file"}


def staff_args(name, w):
    from apps.tasks.tests.factories import make_task

    link = w["a"].client_contacts.first()
    task = make_task(client=w["a"])
    return {
        "inbox_detail": [w["req"].pk], "inbox_convert": [w["req"].pk], "inbox_link": [w["req"].pk],
        "inbox_reply": [w["req"].pk], "inbox_close": [w["req"].pk], "inbox_client": [w["req"].pk],
        "inbox_spam": [w["req"].pk], "inbox_reopen": [w["req"].pk],
        "client_requests": [w["a"].pk], "replace_link": [w["a"].pk],
        "invite": [w["a"].pk, link.pk], "withdraw": [w["a"].pk, link.pk],
        "item_cancel": [w["a"].pk, w["upload"].pk], "task_ask_upload": [task.pk],
        "task_ask_approve": [task.pk], "review": [w["form"].pk], "review_act": [w["form"].pk],
    }.get(name, [])  # fmt: skip


def test_every_staff_address_is_covered(world):
    names = {p.name for p in urlpatterns if not str(p.pattern).startswith(("portal/", "r/"))}
    assert names == set(STAFF_NAMES_GET) | set(STAFF_NAMES_POST) | STAFF_NAMES_OTHER


def test_staff_addresses_send_signed_out_users_to_sign_in(client, world):
    for name in STAFF_NAMES_GET + STAFF_NAMES_POST:
        url = reverse(f"portal:{name}", args=staff_args(name, world))
        method = client.post if name in STAFF_NAMES_POST else client.get
        response = method(url)
        assert response.status_code == 302 and "/login/" in response.url, name
    url = reverse("portal:inbox_file", args=[world["req"].pk, uuid.uuid4()])
    assert client.get(url).status_code == 302


def test_a_portal_user_gets_403_on_every_staff_address(client, world):
    client.force_login(world["user_a"])
    for name in STAFF_NAMES_GET + STAFF_NAMES_POST:
        url = reverse(f"portal:{name}", args=staff_args(name, world))
        method = client.post if name in STAFF_NAMES_POST else client.get
        assert method(url).status_code == 403, name
    url = reverse("portal:inbox_file", args=[world["req"].pk, uuid.uuid4()])
    assert client.get(url).status_code == 403


def test_staff_can_open_the_inbox_pages(client, world):
    sign_in(client, staff())
    for name in ("inbox", "inbox_log", "inbox_detail", "client_requests", "review"):
        url = reverse(f"portal:{name}", args=staff_args(name, world))
        assert client.get(url).status_code == 200, name


def test_staff_sees_the_attachment_only_through_the_view(client, world):
    from apps.portal.tests.helpers import pdf_upload

    request_services.attach_files(world["req"], [pdf_upload()])
    entry = world["req"].files.get()
    assert entry.file.name.startswith("requests/")
    sign_in(client, staff())
    response = client.get(reverse("portal:inbox_file", args=[world["req"].pk, entry.public_id]))
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment")
    assert response["X-Content-Type-Options"] == "nosniff"
