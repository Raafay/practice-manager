"""Letters: a letter template rendered to PDF on the practice letterhead, saved to Documents."""

import base64
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.utils.html import escape, linebreaks

from apps import events
from apps.clients import services as client_services
from apps.clients.models import Document
from apps.core.models import PracticeSettings

from . import merge, services
from .models import Channel, MessageTemplate

LETTER_CSS = """
@page { size: A4; margin: 22mm 20mm 20mm 20mm; }
body { font-family: sans-serif; font-size: 10.5pt; color: #1e293b; line-height: 1.45; }
.head { display: flex; justify-content: space-between; border-bottom: 2px solid %(accent)s;
        padding-bottom: 8px; margin-bottom: 18px; }
.head img { max-height: 48px; }
.practice { font-size: 9pt; color: #475569; text-align: right; }
.practice strong { font-size: 13pt; color: %(accent)s; display: block; }
.date { margin: 16px 0; }
h1 { font-size: 13pt; }
"""


def letterhead_html(practice: PracticeSettings) -> str:
    logo = ""
    if practice.logo:
        try:
            with practice.logo.open("rb") as handle:
                encoded = base64.b64encode(handle.read()).decode()
            logo = (
                f'<img alt="" src="data:{escape(practice.logo_content_type or "image/png")};'
                f'base64,{encoded}">'
            )
        except OSError:
            logo = ""
    contact = " · ".join(x for x in (practice.phone, practice.email) if x)
    return (
        f'<div class="head"><div>{logo}</div><div class="practice">'
        f"<strong>{escape(practice.practice_name)}</strong>"
        f"{linebreaks(escape(practice.address))}<p>{escape(contact)}</p></div></div>"
    )


def render_pdf(html_body: str, practice: PracticeSettings) -> bytes:
    from weasyprint import HTML

    document = (
        "<html><head><meta charset='utf-8'><style>"
        + LETTER_CSS % {"accent": practice.accent_colour}
        + "</style></head><body>"
        + letterhead_html(practice)
        + f"<p class='date'>{timezone.localdate():%d/%m/%Y}</p>"
        + html_body
        + "</body></html>"
    )
    buffer = BytesIO()
    HTML(string=document).write_pdf(buffer)
    return buffer.getvalue()


def create_letter(actor, client, template: MessageTemplate, *, contact=None) -> Document:
    """Render a letter template for a client and save the PDF to Documents."""
    if template.channel != Channel.LETTER:
        raise ValueError("That template is not a letter.")
    ctx = services.build_context(client, user=actor, contact=contact)
    subject, html, _, problems = services.render_template(template, ctx)
    if problems:
        raise ValueError(" ".join(problems))
    practice = PracticeSettings.load()
    body = (f"<h1>{escape(subject)}</h1>" if subject else "") + html
    pdf = render_pdf(body, practice)
    name = f"{template.name} {timezone.localdate():%Y-%m-%d}.pdf"
    upload = SimpleUploadedFile(name, pdf, content_type="application/pdf")
    document = client_services.store_document(
        actor, client, upload, category=Document.Category.CORRESPONDENCE
    )
    events.record(
        actor,
        "letter.created",
        f"{services.who(actor)} created the letter “{template.name}” for {client.name}.",
        client=client,
        target=document,
    )
    return document


__all__ = ["create_letter", "render_pdf", "letterhead_html", "merge"]
