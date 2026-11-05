"""The practice theme: colours as CSS variables, readable contrast, email footer."""


def test_theme_colours_must_keep_white_text_readable():
    import pytest
    from django.core.exceptions import ValidationError

    from apps.core.theme import contrast_with_white, validate_readable_with_white

    assert round(contrast_with_white("#000000"), 1) == 21.0
    validate_readable_with_white("#0f172a")
    validate_readable_with_white("#2f5d8a")
    with pytest.raises(ValidationError):
        validate_readable_with_white("#ffdd55")


def test_pages_and_emails_use_the_practice_theme(db, client, mailoutbox):
    from apps.accounts.tests.factories import owner, sign_in
    from apps.clients.tests.factories import ClientFactory
    from apps.comms import services as comms
    from apps.comms.models import QueuedMessage
    from apps.core.models import PracticeSettings

    practice = PracticeSettings.load()
    practice.brand_colour = "#123456"
    practice.email_footer = "Made Up Accountants Ltd, registered in England 00000000."
    practice.save()
    boss = owner()
    sign_in(client, boss)
    html = client.get("/").content.decode()
    assert "--color-brand: #123456" in html and "bg-brand" in html
    message = comms.create_message(
        ClientFactory(), created_by=boss, to="someone@example.com", subject="Hello",
        body_html="<p>Hello</p>", state=QueuedMessage.State.APPROVED,
    )  # fmt: skip
    comms.send_one(message)
    sent = mailoutbox[-1]
    assert "registered in England 00000000" in sent.body
    assert "registered in England 00000000" in sent.alternatives[0][0]
