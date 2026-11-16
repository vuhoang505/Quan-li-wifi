from __future__ import annotations

from dataclasses import asdict, dataclass

from PySide6.QtCore import QSettings

from ..config import CONFIG, DATA_DIR


@dataclass(slots=True)
class UserSettings:
    refresh_seconds: int = CONFIG.refresh_seconds
    ping_host: str = CONFIG.ping_host
    ping_timeout_ms: int = CONFIG.ping_timeout_ms
    latency_threshold_ms: int = 120
    retention_days: int = 7
    alert_outage: bool = True
    alert_high_latency: bool = True
    alert_new_device: bool = True


class SettingsStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or str(DATA_DIR / "settings.ini")
        self._settings = QSettings(self.path, QSettings.Format.IniFormat)

    @staticmethod
    def _boolean(value: object, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().casefold() in {"1", "true", "yes", "on"}

    @staticmethod
    def _integer(value: object, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def load(self) -> UserSettings:
        defaults = UserSettings()
        return UserSettings(
            refresh_seconds=self._integer(
                self._settings.value("monitor/refresh_seconds", defaults.refresh_seconds),
                defaults.refresh_seconds,
                1,
                60,
            ),
            ping_host=str(self._settings.value("monitor/ping_host", defaults.ping_host)).strip(),
            ping_timeout_ms=self._integer(
                self._settings.value("monitor/ping_timeout_ms", defaults.ping_timeout_ms),
                defaults.ping_timeout_ms,
                300,
                5000,
            ),
            latency_threshold_ms=self._integer(
                self._settings.value("alerts/latency_threshold_ms", defaults.latency_threshold_ms),
                defaults.latency_threshold_ms,
                10,
                5000,
            ),
            retention_days=self._integer(
                self._settings.value("storage/retention_days", defaults.retention_days),
                defaults.retention_days,
                1,
                365,
            ),
            alert_outage=self._boolean(self._settings.value("alerts/outage"), defaults.alert_outage),
            alert_high_latency=self._boolean(self._settings.value("alerts/high_latency"), defaults.alert_high_latency),
            alert_new_device=self._boolean(self._settings.value("alerts/new_device"), defaults.alert_new_device),
        )

    def save(self, settings: UserSettings) -> None:
        values = asdict(settings)
        self._settings.setValue("monitor/refresh_seconds", values["refresh_seconds"])
        self._settings.setValue("monitor/ping_host", values["ping_host"])
        self._settings.setValue("monitor/ping_timeout_ms", values["ping_timeout_ms"])
        self._settings.setValue("alerts/latency_threshold_ms", values["latency_threshold_ms"])
        self._settings.setValue("storage/retention_days", values["retention_days"])
        self._settings.setValue("alerts/outage", values["alert_outage"])
        self._settings.setValue("alerts/high_latency", values["alert_high_latency"])
        self._settings.setValue("alerts/new_device", values["alert_new_device"])
        self._settings.sync()

