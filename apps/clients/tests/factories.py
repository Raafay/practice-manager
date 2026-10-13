"""Factories for clients and people. Everything here is invented."""

import factory

from apps.clients.models import Client, ClientContact, Contact, Document, Note, Tag


class ClientFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Client

    name = factory.Sequence(lambda n: f"Sample Client {n} Ltd")
    client_type = Client.Type.LTD
    status = Client.Status.ACTIVE


class ContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Contact

    first_name = factory.Sequence(lambda n: f"First{n}")
    last_name = factory.Sequence(lambda n: f"Last{n}")
    email = factory.LazyAttribute(lambda o: f"{o.first_name}.{o.last_name}@example.com".lower())


class ClientContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ClientContact

    client = factory.SubFactory(ClientFactory)
    contact = factory.SubFactory(ContactFactory)


class TagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tag
        django_get_or_create = ["name"]

    name = factory.Sequence(lambda n: f"Tag {n}")


class NoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Note

    client = factory.SubFactory(ClientFactory)
    text = "A sample note."


class DocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Document

    client = factory.SubFactory(ClientFactory)
    title = factory.Sequence(lambda n: f"Document {n}")
    original_name = "sample.txt"
    content_type = "text/plain"
    file = factory.django.FileField(filename="sample.txt", data=b"made up text")
    size = 12
