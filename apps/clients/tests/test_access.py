"""Every address in the clients app: signed out goes to sign-in, a portal user gets 403,
and rights-gated pages refuse staff without the right."""

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import manager, owner, portal_user, sign_in, staff
from apps.clients.models import ClientLink

from .factories import (
    ClientContactFactory,
    ClientFactory,
    DocumentFactory,
    NoteFactory,
    TagFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    link = ClientContactFactory(is_main=True)
    other = ClientFactory()
    client_link = ClientLink.objects.create(client_a=link.client, client_b=other)
    return {
        "client": link.client,
        "link": link,
        "contact": link.contact,
        "other": other,
        "client_link": client_link,
        "note": NoteFactory(client=link.client),
        "document": DocumentFactory(client=link.client),
        "tag": TagFactory(),
    }


def addresses(w):
    c, link, contact = w["client"].pk, w["link"].pk, w["contact"].pk
    doc = w["document"].public_id
    return [
        # (name, args, method)
        ("clients:list", [], "get"),
        ("clients:new", [], "get"),
        ("clients:export", [], "get"),
        ("clients:view_save", [], "post"),
        ("clients:search_dropdown", [], "get"),
        ("clients:search", [], "get"),
        ("clients:detail", [c], "get"),
        ("clients:timeline", [c], "get"),
        ("clients:contacts", [c], "get"),
        ("clients:links", [c], "get"),
        ("clients:documents", [c], "get"),
        ("clients:panel", [c, "required"], "get"),
        ("clients:panel_edit", [c, "required"], "get"),
        ("clients:client_reveal", [c, "company_utr"], "post"),
        ("clients:status", [c], "get"),
        ("clients:archive", [c], "get"),
        ("clients:restore", [c], "post"),
        ("clients:delete", [c], "get"),
        ("clients:add_note", [c], "get"),
        ("clients:log_call", [c], "get"),
        ("clients:pin_note", [c, w["note"].pk], "post"),
        ("clients:contact_add", [c], "get"),
        ("clients:contact_link", [c, w["other"].pk], "post"),
        ("clients:contact_edit", [c, link], "get"),
        ("clients:contact_unlink", [c, link], "post"),
        ("clients:link_add", [c], "get"),
        ("clients:link_remove", [c, w["client_link"].pk], "post"),
        ("clients:contact_detail", [contact], "get"),
        ("clients:contact_detail_edit", [contact], "get"),
        ("clients:contact_reveal", [contact, "ni_number"], "post"),
        ("clients:personal_tax_client", [contact], "post"),
        ("clients:document_upload", [c], "post"),
        ("clients:document_download", [doc], "get"),
        ("clients:document_preview", [doc], "get"),
        ("clients:document_edit", [doc], "get"),
        ("clients:document_delete", [doc], "post"),
        ("clients:document_purge", [doc], "post"),
        ("clients:tags", [], "get"),
        ("clients:tag_add", [], "get"),
        ("clients:tag_edit", [w["tag"].pk], "get"),
        ("clients:tag_delete", [w["tag"].pk], "post"),
        ("clients:custom_fields", [], "get"),
        ("clients:custom_field_add", [], "get"),
    ]


def test_every_address_sends_signed_out_users_to_sign_in(client, world):
    for name, args, method in addresses(world):
        response = getattr(client, method)(reverse(name, args=args))
        assert response.status_code == 302, name
        assert "/login/" in response["Location"], name


def test_every_address_refuses_portal_users(client, world):
    sign_in(client, portal_user())
    for name, args, method in addresses(world):
        response = getattr(client, method)(reverse(name, args=args))
        assert response.status_code == 403, name


@pytest.mark.parametrize(
    ("name", "method", "who"),
    [
        ("clients:export", "get", staff),
        ("clients:status", "get", staff),
        ("clients:archive", "get", staff),
        ("clients:restore", "post", staff),
        ("clients:delete", "get", manager),
        ("clients:tags", "get", staff),
        ("clients:custom_fields", "get", staff),
    ],
)
def test_pages_that_need_a_right_refuse_everyone_without_it(client, world, name, method, who):
    sign_in(client, who())
    args = (
        [world["client"].pk]
        if name.startswith("clients:")
        and "tags" not in name
        and "custom" not in name
        and "export" not in name
        else []
    )
    assert getattr(client, method)(reverse(name, args=args)).status_code == 403


def test_the_owner_purge_address_refuses_a_manager(client, world):
    sign_in(client, manager())
    response = client.post(reverse("clients:document_purge", args=[world["document"].public_id]))
    assert response.status_code == 403


def test_staff_can_open_the_main_pages(client, world):
    sign_in(client, owner())
    for name, args in [
        ("clients:list", []),
        ("clients:detail", [world["client"].pk]),
        ("clients:timeline", [world["client"].pk]),
        ("clients:contacts", [world["client"].pk]),
        ("clients:links", [world["client"].pk]),
        ("clients:documents", [world["client"].pk]),
        ("clients:contact_detail", [world["contact"].pk]),
        ("clients:tags", []),
        ("clients:custom_fields", []),
        ("clients:new", []),
    ]:
        response = client.get(reverse(name, args=args))
        assert response.status_code == 200, name


def test_unknown_client_is_404(client):
    sign_in(client, staff())
    assert client.get(reverse("clients:detail", args=[999999])).status_code == 404
