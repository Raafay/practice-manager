import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounts.tests.factories import manager, sign_in, staff
from apps.aml import services
from apps.aml.models import IdentityCheck
from apps.clients import services as client_services
from apps.clients.tests.factories import ClientContactFactory, ClientFactory, ContactFactory
from apps.events.models import ActivityEvent

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40


def png(name="id.png"):
    return SimpleUploadedFile(name, PNG, content_type="image/png")


def company_with_people():
    client = ClientFactory(status="prospect", client_type="ltd")
    main = ContactFactory(first_name="Maria", last_name="Main")
    director = ContactFactory(first_name="Dev", last_name="Director")
    owner_ = ContactFactory(first_name="Olive", last_name="Owner")
    bookkeeper = ContactFactory(first_name="Bo", last_name="Books")
    ClientContactFactory(client=client, contact=main, is_main=True, roles=["employee"])
    ClientContactFactory(client=client, contact=director, roles=["director"])
    ClientContactFactory(
        client=client, contact=owner_, roles=["shareholder"], shareholding_percent=40
    )
    ClientContactFactory(client=client, contact=bookkeeper, roles=["bookkeeper"])
    client_services.change_status(manager(), client, "onboarding")
    return client, main, director, owner_, bookkeeper


def test_people_to_identify_come_from_roles_and_ownership():
    client, main, director, owner_, bookkeeper = company_with_people()
    people = {c.pk: reasons for c, reasons in services.proposed_people(client)}
    assert set(people) == {main.pk, director.pk, owner_.pk}
    assert "Main contact" in people[main.pk]
    assert "Director" in people[director.pk]
    assert "Owner with more than 25%" in people[owner_.pk]
    assert services.sync_checks(client) == 3
    assert services.sync_checks(client) == 0


def test_a_psc_is_listed_and_a_resigned_director_is_not():
    client, main, director, owner_, bookkeeper = company_with_people()
    psc = ContactFactory()
    ClientContactFactory(client=client, contact=psc, roles=["psc"])
    gone = ContactFactory()
    ClientContactFactory(client=client, contact=gone, roles=["director"], resigned_on="2025-01-01")
    pks = {c.pk for c, _ in services.proposed_people(client)}
    assert psc.pk in pks and gone.pk not in pks


def test_verified_needs_method_document_type_and_an_uploaded_copy():
    client, main, *_ = company_with_people()
    services.sync_checks(client)
    check = IdentityCheck.objects.get(client=client, contact=main)
    with pytest.raises(ValidationError, match="how the identity"):
        services.update_check(manager(), check, {"state": "verified"})
    with pytest.raises(ValidationError, match="Upload a copy"):
        services.update_check(
            manager(),
            check,
            {"state": "verified", "method": "in_person", "document_type": "passport"},
        )
    services.upload_for_check(manager(), check, png())
    check.refresh_from_db()
    assert check.state == "received"
    services.update_check(
        manager(), check, {"state": "verified", "method": "in_person", "document_type": "passport"}
    )
    check.refresh_from_db()
    assert check.state == "verified" and check.verified_at is not None


def test_uploads_are_sensitive_documents_and_each_view_is_logged(client):
    c, main, *_ = company_with_people()
    services.sync_checks(c)
    check = IdentityCheck.objects.get(client=c, contact=main)
    document = services.upload_for_check(manager(), check, png())
    address = services.upload_for_check(manager(), check, png("bill.png"), proof_of_address=True)
    assert document.sensitive and document.category == "identity"
    assert address.sensitive and address.category == "proof_of_address"
    viewer = manager()
    sign_in(client, viewer)
    assert (
        client.get(reverse("clients:document_download", args=[document.public_id])).status_code
        == 200
    )
    assert ActivityEvent.objects.filter(verb="document.downloaded", client=c).exists()
    client.get(reverse("clients:document_preview", args=[document.public_id]))
    assert ActivityEvent.objects.filter(verb="document.viewed", client=c).exists()
    # Staff without the right cannot open it, and nothing more is logged.
    role = Role.objects.get(slug=Role.STAFF)
    role.rights = [r for r in role.rights if r != "documents.sensitive"]
    role.save()
    before = ActivityEvent.objects.filter(verb="document.downloaded").count()
    sign_in(client, staff())
    response = client.get(reverse("clients:document_download", args=[document.public_id]))
    assert response.status_code == 403
    assert ActivityEvent.objects.filter(verb="document.downloaded").count() == before


def test_checklist_line_ticks_when_everyone_is_verified_and_untick_when_added():
    client, main, director, owner_, bookkeeper = company_with_people()
    services.sync_checks(client)
    boss = manager()
    for check in services.listed_checks(client):
        services.upload_for_check(boss, check, png())
        services.update_check(
            boss, check, {"state": "verified", "method": "in_person", "document_type": "passport"}
        )
    line = client.onboarding_items.get(key="identity_verified")
    assert line.state == "done"
    services.add_person(boss, client, bookkeeper, "Signs the bank mandate")
    line.refresh_from_db()
    assert line.state == "todo"


def test_people_can_be_added_and_removed_only_with_a_reason():
    client, main, director, owner_, bookkeeper = company_with_people()
    services.sync_checks(client)
    with pytest.raises(ValidationError):
        services.add_person(manager(), client, bookkeeper, " ")
    check = services.add_person(manager(), client, bookkeeper, "Signs the bank mandate")
    assert check.added_by_hand
    with pytest.raises(ValidationError):
        services.remove_person(manager(), check, "")
    services.remove_person(manager(), check, "Left the business")
    check.refresh_from_db()
    assert check.excluded
    assert ActivityEvent.objects.filter(verb="aml.person_removed").exists()


def test_identity_pages_need_sign_in_and_the_right_client(client):
    c, main, *_ = company_with_people()
    services.sync_checks(c)
    check = IdentityCheck.objects.get(client=c, contact=main)
    url = reverse("aml:identity", args=[c.pk, check.pk])
    assert client.get(url).status_code == 302
    sign_in(client, staff())
    assert client.get(url).status_code == 200
    other = ClientFactory()
    assert client.get(reverse("aml:identity", args=[other.pk, check.pk])).status_code == 404
    # Without the sensitive-documents right, an upload is refused.
    role = Role.objects.get(slug=Role.STAFF)
    role.rights = [r for r in role.rights if r != "documents.sensitive"]
    role.save()
    assert client.post(url, {"state": "received", "id_file": png()}).status_code == 403
    assert not check.documents.exists()


def test_the_provider_interface_has_nothing_behind_it():
    from apps.aml import providers

    assert providers.get_provider() is None
