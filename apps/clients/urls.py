from django.urls import path

from . import views, views_contacts, views_documents, views_retention, views_settings

app_name = "clients"

urlpatterns = [
    path("settings/retention/", views_retention.RetentionReportView.as_view(), name="retention"),
    path(
        "contacts/<int:pk>/export/",
        views_retention.ContactExportView.as_view(),
        name="contact_export",
    ),
    path(
        "contacts/<int:pk>/remove/",
        views_retention.ContactPurgeView.as_view(),
        name="contact_purge",
    ),
    path("clients/", views.ClientListView.as_view(), name="list"),
    path("clients/new/", views.ClientCreateView.as_view(), name="new"),
    path("clients/export/", views.ClientExportView.as_view(), name="export"),
    path("clients/views/save/", views.SavedViewCreateView.as_view(), name="view_save"),
    path("clients/views/<int:pk>/delete/", views.SavedViewDeleteView.as_view(), name="view_delete"),
    path("clients/search/", views.SearchDropdownView.as_view(), name="search_dropdown"),
    path("search/", views.SearchResultsView.as_view(), name="search"),
    # One client
    path("clients/<int:pk>/", views.ClientDetailView.as_view(), name="detail"),
    path("clients/<int:pk>/timeline/", views.ClientTimelineView.as_view(), name="timeline"),
    path("clients/<int:pk>/contacts/", views.ClientContactsView.as_view(), name="contacts"),
    path("clients/<int:pk>/links/", views.ClientLinksView.as_view(), name="links"),
    path("clients/<int:pk>/documents/", views.ClientDocumentsView.as_view(), name="documents"),
    path("clients/<int:pk>/panels/<str:key>/", views.PanelView.as_view(), name="panel"),
    path(
        "clients/<int:pk>/panels/<str:key>/edit/", views.PanelEditView.as_view(), name="panel_edit"
    ),
    path(
        "clients/<int:pk>/reveal/<str:field>/",
        views.ClientRevealView.as_view(),
        name="client_reveal",
    ),
    path("clients/<int:pk>/status/", views.ChangeStatusView.as_view(), name="status"),
    path("clients/<int:pk>/archive/", views.ArchiveView.as_view(), name="archive"),
    path("clients/<int:pk>/restore/", views.RestoreView.as_view(), name="restore"),
    path("clients/<int:pk>/delete/", views.DeleteView.as_view(), name="delete"),
    path("clients/<int:pk>/notes/add/", views.AddNoteView.as_view(), name="add_note"),
    path("clients/<int:pk>/calls/add/", views.LogCallView.as_view(), name="log_call"),
    path("clients/<int:pk>/notes/<int:note_pk>/pin/", views.PinNoteView.as_view(), name="pin_note"),
    # People on a client
    path(
        "clients/<int:pk>/contacts/add/",
        views_contacts.ContactAddView.as_view(),
        name="contact_add",
    ),
    path(
        "clients/<int:pk>/contacts/link/<int:contact_pk>/",
        views_contacts.ContactLinkView.as_view(),
        name="contact_link",
    ),
    path(
        "clients/<int:pk>/contacts/<int:link_pk>/edit/",
        views_contacts.ClientContactEditView.as_view(),
        name="contact_edit",
    ),
    path(
        "clients/<int:pk>/contacts/<int:link_pk>/unlink/",
        views_contacts.ClientContactUnlinkView.as_view(),
        name="contact_unlink",
    ),
    # Related clients
    path("clients/<int:pk>/links/add/", views_contacts.LinkAddView.as_view(), name="link_add"),
    path(
        "clients/<int:pk>/links/<int:link_pk>/remove/",
        views_contacts.LinkRemoveView.as_view(),
        name="link_remove",
    ),
    # People
    path("contacts/<int:pk>/", views_contacts.ContactDetailView.as_view(), name="contact_detail"),
    path(
        "contacts/<int:pk>/edit/",
        views_contacts.ContactEditView.as_view(),
        name="contact_detail_edit",
    ),
    path(
        "contacts/<int:pk>/reveal/<str:field>/",
        views_contacts.ContactRevealView.as_view(),
        name="contact_reveal",
    ),
    path(
        "contacts/<int:pk>/personal-tax-client/",
        views_contacts.PersonalTaxClientView.as_view(),
        name="personal_tax_client",
    ),
    # Documents
    path(
        "clients/<int:pk>/documents/upload/",
        views_documents.DocumentUploadView.as_view(),
        name="document_upload",
    ),
    path(
        "documents/<uuid:public_id>/download/",
        views_documents.DocumentDownloadView.as_view(),
        name="document_download",
    ),
    path(
        "documents/<uuid:public_id>/view/",
        views_documents.DocumentPreviewView.as_view(),
        name="document_preview",
    ),
    path(
        "documents/<uuid:public_id>/edit/",
        views_documents.DocumentEditView.as_view(),
        name="document_edit",
    ),
    path(
        "documents/<uuid:public_id>/delete/",
        views_documents.DocumentDeleteView.as_view(),
        name="document_delete",
    ),
    path(
        "documents/<uuid:public_id>/purge/",
        views_documents.DocumentPurgeView.as_view(),
        name="document_purge",
    ),
    # Settings
    path("settings/tags/", views_settings.TagListView.as_view(), name="tags"),
    path("settings/tags/add/", views_settings.TagEditView.as_view(), name="tag_add"),
    path("settings/tags/<int:pk>/edit/", views_settings.TagEditView.as_view(), name="tag_edit"),
    path(
        "settings/tags/<int:pk>/delete/", views_settings.TagDeleteView.as_view(), name="tag_delete"
    ),
    path(
        "settings/custom-fields/",
        views_settings.CustomFieldListView.as_view(),
        name="custom_fields",
    ),
    path(
        "settings/custom-fields/add/",
        views_settings.CustomFieldEditView.as_view(),
        name="custom_field_add",
    ),
    path(
        "settings/custom-fields/<int:pk>/edit/",
        views_settings.CustomFieldEditView.as_view(),
        name="custom_field_edit",
    ),
    path(
        "settings/custom-fields/<int:pk>/delete/",
        views_settings.CustomFieldDeleteView.as_view(),
        name="custom_field_delete",
    ),
]
