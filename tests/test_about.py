"""Tests for the About dialog and its menu entry."""

import os
import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication                     # noqa: E402

import pulse_monitor as pm                                     # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def about(qapp):
    dlg = pm.AboutDialog()
    yield dlg
    dlg.close()
    dlg.deleteLater()
    qapp.processEvents()


def test_app_version_is_a_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", pm.APP_VERSION)
    assert pm.APP_VERSION == "1.0.4"


def test_about_links_to_the_project_fork():
    assert pm.GITHUB_URL == (
        "https://github.com/quantumblow/strix-pulse-monitor")


def test_about_dialog_is_locked_and_large(about):
    # A fixed width alone let the WM resize only the height; the whole box is
    # locked now, and it is laid out large enough to read.
    assert about.minimumSize() == about.maximumSize()
    assert about.width() >= 660
    assert about.height() >= 430


def test_about_dialog_shows_name_and_version_on_one_line(about):
    text = about.version_label.text()
    assert pm.APP_NAME in text
    assert pm.APP_VERSION in text
    assert "\n" not in text


def test_about_dialog_has_a_github_button(about):
    assert not about.github_btn.icon().isNull()
    assert about.github_btn.toolTip() == pm._("Open the GitHub repository")


def test_github_button_opens_the_repository(about, monkeypatch):
    opened = []
    monkeypatch.setattr(pm, "_open_url",
                        lambda url: opened.append(url) or True)
    about.github_btn.click()
    assert opened == [pm.GITHUB_URL]


def test_about_entry_is_in_the_tray_menu(qapp, monkeypatch):
    try:
        os.unlink(pm.CONFIG_FILE)
    except OSError:
        pass
    w = pm.PulseWidget()
    try:
        texts = [a.text() for a in w.tray.contextMenu().actions()]
        assert w.act_about.text() == pm._("About")
        assert w.act_about.text() in texts

        # The action really opens the modal About box (fake it so the test
        # never blocks in exec()).
        called = []

        class FakeAbout:
            def __init__(self, parent=None):
                called.append(parent)

            def exec(self):
                called.append("exec")

        monkeypatch.setattr(pm, "AboutDialog", FakeAbout)
        w.act_about.trigger()
        assert called == [w, "exec"]
    finally:
        w.tray.hide()
        w.hide()
        w.deleteLater()
        qapp.processEvents()
