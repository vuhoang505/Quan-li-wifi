from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from ..core.discovery import scan_lan
from ..core.network import WifiInfo, default_gateway, dns_servers, ping, primary_interface, wifi_info
from ..router import GenericRouterAdapter


class PingWorker(QObject):
    finished = Signal(object)

    def __init__(self, host: str, timeout_ms: int) -> None:
        super().__init__()
        self.host = host
        self.timeout_ms = timeout_ms

    @Slot()
    def run(self) -> None:
        self.finished.emit(ping(self.host, self.timeout_ms))


class ScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(scan_lan())
        except Exception as exc:
            self.failed.emit(str(exc))


class SystemInfoWorker(QObject):
    finished = Signal(object)

    @Slot()
    def run(self) -> None:
        try:
            result = (wifi_info(), primary_interface(), default_gateway(), dns_servers())
        except Exception as exc:
            result = (WifiInfo(error=f"Không thể đọc thông tin hệ thống: {exc}"), None, None, [])
        self.finished.emit(result)


class RouterDetectWorker(QObject):
    finished = Signal(object)

    def __init__(self, host: str) -> None:
        super().__init__()
        self.host = host

    @Slot()
    def run(self) -> None:
        try:
            adapter = GenericRouterAdapter(self.host)
            reachable = adapter.detect()
            info = adapter.get_router_info()
            result = {
                "host": self.host,
                "reachable": reachable,
                "url": info.management_url,
                "reason": info.capabilities.reason,
            }
        except Exception as exc:
            result = {
                "host": self.host,
                "reachable": False,
                "url": None,
                "reason": f"Lỗi kiểm tra cổng quản trị: {exc}",
            }
        self.finished.emit(result)

