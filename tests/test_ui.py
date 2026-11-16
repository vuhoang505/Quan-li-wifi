from __future__ import annotations

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from wifi_guardian.database import Repository
from wifi_guardian.ui.main_window import MainWindow
from wifi_guardian.ui.pages import TrafficAnalyticsPage
from wifi_guardian.ui.settings_store import UserSettings


class MemorySettingsStore:
    def __init__(self) -> None:
        self.value = UserSettings()

    def load(self) -> UserSettings:
        return self.value

    def save(self, settings: UserSettings) -> None:
        self.value = settings


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_all_navigation_pages_are_functional_widgets() -> None:
    app = _app()
    store = MemorySettingsStore()
    window = MainWindow(Repository("sqlite:///:memory:"), store)  # type: ignore[arg-type]
    window.timer.stop()
    names = [window.stack.widget(index).__class__.__name__ for index in range(window.stack.count())]
    assert names == [
        "DashboardPage",
        "DevicesPage",
        "RouterPage",
        "WifiInfoPage",
        "TopologyPage",
        "TrafficAnalyticsPage",
        "AutomationPage",
        "SecurityPage",
        "SettingsPage",
    ]
    changed = replace(store.value, refresh_seconds=7, ping_host="9.9.9.9")
    window.apply_settings(changed)
    assert window.timer.interval() == 7000
    assert store.value.ping_host == "9.9.9.9"
    window.deleteLater()
    app.processEvents()


def test_traffic_page_reads_real_repository_samples() -> None:
    app = _app()
    repository = Repository("sqlite:///:memory:")
    repository.add_sample(1024, 512, 20, 0)
    repository.add_sample(3072, 1536, 40, 0)
    page = TrafficAnalyticsPage(repository)
    page.reload()
    assert "2.0 KB/s" in page.average_down.text()
    assert "30 ms" in page.average_latency.text()
    page.deleteLater()
    app.processEvents()

