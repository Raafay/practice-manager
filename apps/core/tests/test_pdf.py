import builtins

import pytest

from apps.core import pdf

real_import = builtins.__import__


@pytest.fixture
def no_pango(monkeypatch):
    def fake_import(name, *args, **kwargs):
        if name == "weasyprint":
            raise OSError("cannot load library 'libgobject-2.0-0'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_development_uses_a_stand_in_pdf_without_pango(no_pango, settings):
    settings.DEBUG = True
    assert pdf.weasyprint_html() is None
    assert pdf.PLACEHOLDER_PDF.startswith(b"%PDF-")


def test_live_site_never_uses_the_stand_in(no_pango, settings):
    settings.DEBUG = False
    with pytest.raises(OSError):
        pdf.weasyprint_html()


def test_weasyprint_is_used_when_it_loads(settings):
    from weasyprint import HTML

    settings.DEBUG = True
    assert pdf.weasyprint_html() is HTML
