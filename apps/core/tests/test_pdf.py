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


def test_a_mac_is_pointed_at_homebrews_pango(monkeypatch):
    monkeypatch.setattr(pdf.os.path, "isdir", lambda path: path == pdf.HOMEBREW_LIB)
    environ = {"DYLD_FALLBACK_LIBRARY_PATH": "/somewhere/lib"}
    pdf.point_at_homebrew(platform="darwin", environ=environ)
    assert environ["DYLD_FALLBACK_LIBRARY_PATH"] == "/somewhere/lib:/opt/homebrew/lib"
    pdf.point_at_homebrew(platform="darwin", environ=environ)
    assert environ["DYLD_FALLBACK_LIBRARY_PATH"] == "/somewhere/lib:/opt/homebrew/lib"


def test_other_systems_are_left_alone(monkeypatch):
    monkeypatch.setattr(pdf.os.path, "isdir", lambda path: True)
    environ = {}
    pdf.point_at_homebrew(platform="linux", environ=environ)
    assert environ == {}
