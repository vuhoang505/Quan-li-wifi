from __future__ import annotations

import math
import time
import webbrowser
from collections import deque
from datetime import datetime, timezone

import pyqtgraph as pg
from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import CONFIG
from ..core.network import InterfaceInfo, PingResult, TrafficMeter, WifiInfo
from ..database import Repository
from .pages import AutomationPage, SecurityPage, SettingsPage, TrafficAnalyticsPage, WifiInfoPage
from .settings_store import SettingsStore, UserSettings
from .theme import THEME
from .workers import PingWorker, RouterDetectWorker, ScanWorker, SystemInfoWorker


def human_rate(value: float) -> str:
    units = ("B/s", "KB/s", "MB/s", "GB/s")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.1f} {units[index]}"


def title(text: str, subtitle: str) -> QVBoxLayout:
    layout = QVBoxLayout()
    heading = QLabel(text)
    heading.setObjectName("PageTitle")
    detail = QLabel(subtitle)
    detail.setObjectName("Muted")
    detail.setWordWrap(True)
    layout.addWidget(heading)
    layout.addWidget(detail)
    return layout


class MetricCard(QFrame):
    def __init__(self, label: str, value: str = "—") -> None:
        super().__init__()
        self.setObjectName("Card")
        box = QVBoxLayout(self)
        caption = QLabel(label.upper())
        caption.setObjectName("Muted")
        self.value = QLabel(value)
        self.value.setObjectName("CardValue")
        box.addWidget(caption)
        box.addWidget(self.value)


class DashboardPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.addLayout(title("Tổng quan mạng", "Số liệu trực tiếp từ máy tính này, không phải tốc độ Internet do nhà mạng cam kết."))
        cards = QHBoxLayout()
        self.download = MetricCard("Tải xuống")
        self.upload = MetricCard("Tải lên")
        self.latency = MetricCard("Độ trễ")
        self.status = MetricCard("Máy chủ kiểm tra")
        for card in (self.download, self.upload, self.latency, self.status):
            cards.addWidget(card)
        root.addLayout(cards)

        info = QFrame()
        info.setObjectName("Card")
        info_layout = QHBoxLayout(info)
        self.ssid = QLabel("Wi‑Fi: đang đọc…")
        self.adapter = QLabel("Adapter: đang đọc…")
        self.gateway = QLabel("Gateway: đang đọc…")
        self.dns = QLabel("DNS: đang đọc…")
        for label in (self.ssid, self.adapter, self.gateway, self.dns):
            info_layout.addWidget(label)
        root.addWidget(info)

        self.plot = pg.PlotWidget()
        self.plot.setBackground("#0d1629")
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setLabel("left", "Lưu lượng", units="B/s")
        self.plot.setLabel("bottom", "Mẫu gần nhất")
        self.download_curve = self.plot.plot(pen=pg.mkPen("#55e7ff", width=2), name="Download")
        self.upload_curve = self.plot.plot(pen=pg.mkPen("#a978ff", width=2), name="Upload")
        self.plot.addLegend()
        root.addWidget(self.plot, 1)

    def set_network_info(
        self,
        wifi: WifiInfo,
        interface: InterfaceInfo | None,
        gateway: str | None,
        dns: list[str],
    ) -> None:
        self.ssid.setText(f"Wi‑Fi: {wifi.ssid or 'Không khả dụng'}")
        if interface:
            self.adapter.setText(f"Adapter: {interface.name} · {interface.ipv4 or interface.ipv6}")
        else:
            self.adapter.setText("Adapter: Không có kết nối hoạt động")
        self.gateway.setText(f"Gateway: {gateway or 'Không xác định'}")
        self.dns.setText(f"DNS: {', '.join(dns) if dns else 'Không xác định'}")


class DevicesPage(QWidget):
    scan_requested = Signal()

    def __init__(self, repository: Repository) -> None:
        super().__init__()
        self.repository = repository
        root = QVBoxLayout(self)
        root.addLayout(title("Thiết bị đã phát hiện", "Lịch sử quan sát trong dải LAN hiện tại. Không xuất hiện ở lần quét mới không đồng nghĩa chắc chắn offline."))
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm IP, MAC, tên thiết bị…")
        self.search.textChanged.connect(self._filter)
        self.scan = QPushButton("Quét mạng LAN")
        self.scan.setObjectName("Primary")
        self.scan.clicked.connect(self.scan_requested)
        tools.addWidget(self.search, 1)
        tools.addWidget(self.scan)
        root.addLayout(tools)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Tên", "IP", "MAC", "Hostname", "Nguồn", "Lần cuối thấy"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table)
        hint = QLabel("Nhấp đúp một dòng để đặt tên riêng cho thiết bị.")
        hint.setObjectName("Muted")
        root.addWidget(hint)
        self.table.cellDoubleClicked.connect(self._rename)
        self.reload()

    def reload(self) -> None:
        devices = self.repository.devices()
        self.table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            values = (
                device.custom_name or device.hostname or "Thiết bị chưa đặt tên",
                device.ip_address,
                device.mac_address,
                device.hostname or "—",
                device.source,
                self._local_time(device.last_seen),
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, device.mac_address)
                self.table.setItem(row, col, item)
        self._filter(self.search.text())

    @staticmethod
    def _local_time(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone().strftime("%d/%m/%Y %H:%M:%S")

    def _filter(self, text: str) -> None:
        needle = text.casefold().strip()
        for row in range(self.table.rowCount()):
            haystack = " ".join(
                self.table.item(row, col).text() for col in range(self.table.columnCount())
            ).casefold()
            self.table.setRowHidden(row, needle not in haystack)

    def _rename(self, row: int, _column: int) -> None:
        mac = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        dialog = QDialog(self)
        dialog.setWindowTitle("Đặt tên thiết bị")
        layout = QVBoxLayout(dialog)
        field = QLineEdit(self.table.item(row, 0).text())
        save = QPushButton("Lưu")
        save.setObjectName("Primary")
        layout.addWidget(QLabel(f"Thiết bị {mac}"))
        layout.addWidget(field)
        layout.addWidget(save)
        save.clicked.connect(dialog.accept)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.repository.rename_device(mac, field.text())
            self.reload()


class RouterPage(QWidget):
    detect_requested = Signal(str)

    def __init__(self, repository: Repository) -> None:
        super().__init__()
        self.repository = repository
        root = QVBoxLayout(self)
        root.addLayout(title("Quản lý router", "Chế độ an toàn chỉ đọc. Chức năng quản trị chỉ xuất hiện khi model, firmware và API đã được xác minh."))
        form_card = QFrame()
        form_card.setObjectName("Card")
        form = QFormLayout(form_card)
        self.host = QLineEdit("")
        self.host.setPlaceholderText("Ví dụ: 192.168.1.1")
        self.result = QLabel("Chưa kiểm tra")
        self.result.setWordWrap(True)
        self.detect_button = QPushButton("Kiểm tra cổng quản trị")
        self.detect_button.setObjectName("Primary")
        self.open_button = QPushButton("Mở trang quản trị")
        self.open_button.setEnabled(False)
        self.detect_button.clicked.connect(self.detect)
        self.open_button.clicked.connect(self.open_management)
        self.host.textChanged.connect(self._invalidate_result)
        form.addRow("Địa chỉ gateway", self.host)
        form.addRow("Khả năng", self.result)
        form.addRow(self.detect_button, self.open_button)
        root.addWidget(form_card)
        warning = QLabel(
            "WiFi Guardian không đoán API, không vượt xác thực và không dùng deauthentication. "
            "Trong bản này, adapter Generic chỉ mở giao diện chính thức của router."
        )
        warning.setWordWrap(True)
        warning.setObjectName("Muted")
        root.addWidget(warning)
        root.addStretch()

    def detect(self) -> None:
        host = self.host.text().strip()
        if not host:
            self.result.setText("Hãy nhập địa chỉ IPv4 trong LAN.")
            return
        self.detect_button.setEnabled(False)
        self.result.setText("Đang kiểm tra HTTPS/HTTP trong luồng nền…")
        self.detect_requested.emit(host)

    def set_gateway(self, gateway: str | None) -> None:
        if gateway and not self.host.text().strip():
            self.host.setText(gateway)

    def _invalidate_result(self) -> None:
        self._management_url = None
        self.open_button.setEnabled(False)

    def set_detect_result(self, result: dict[str, object]) -> None:
        self.detect_button.setEnabled(True)
        if str(result["host"]) != self.host.text().strip():
            self.result.setText("Địa chỉ đã thay đổi; hãy kiểm tra lại.")
            return
        reachable = bool(result["reachable"])
        self._management_url = str(result["url"]) if result.get("url") else None
        self.open_button.setEnabled(reachable and self._management_url is not None)
        self.result.setText(
            (f"Cổng quản trị phản hồi tại {self._management_url}. " if reachable else "Không nhận được phản hồi từ cổng HTTPS/HTTP. ")
            + str(result["reason"])
        )
        self.repository.audit(
            "router_detect",
            str(result["host"]),
            "ok" if reachable else "unreachable",
            self._management_url or "",
        )

    def open_management(self) -> None:
        if not getattr(self, "_management_url", None):
            QMessageBox.warning(self, "Không thể mở", "Hãy kiểm tra cổng quản trị trước.")
            return
        answer = QMessageBox.question(
            self,
            "Mở giao diện router",
            f"Mở {self._management_url} bằng trình duyệt? WiFi Guardian không tự đăng nhập.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            webbrowser.open(self._management_url)
            self.repository.audit("open_router_ui", self._management_url, "confirmed")


class TopologyView(QGraphicsView):
    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        event.accept()


class TopologyPage(QWidget):
    def __init__(self, repository: Repository) -> None:
        super().__init__()
        self.repository = repository
        root = QVBoxLayout(self)
        root.addLayout(title("Sơ đồ mạng", "Các đường nối biểu thị thiết bị được phát hiện trong cùng LAN, không khẳng định kết nối vật lý trực tiếp."))
        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self._selection_changed)
        self.view = TopologyView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        root.addWidget(self.view)
        self.detail = QLabel("Chọn một thiết bị để xem IP, MAC và nguồn phát hiện.")
        self.detail.setObjectName("Muted")
        root.addWidget(self.detail)
        refresh = QPushButton("Làm mới sơ đồ")
        refresh.clicked.connect(self.reload)
        root.addWidget(refresh)
        self.reload()

    def reload(self) -> None:
        self.scene.clear()
        center_x, center_y = 350, 230
        lan = QGraphicsEllipseItem(center_x - 45, center_y - 45, 90, 90)
        lan.setBrush(QColor("#116783"))
        lan.setPen(QPen(QColor("#61e8ff"), 2))
        lan.setToolTip("Dải LAN được phát hiện; không biểu diễn kết nối vật lý.")
        self.scene.addItem(lan)
        lan_text = self.scene.addText("MẠNG LAN")
        lan_text.setDefaultTextColor(QColor("white"))
        lan_text.setPos(center_x - 36, center_y - 10)
        devices = self.repository.devices()
        count = max(len(devices), 1)
        for index, device in enumerate(devices):
            angle = 2 * math.pi * index / count
            x = center_x + math.cos(angle) * 250
            y = center_y + math.sin(angle) * 160
            line = QGraphicsLineItem(center_x, center_y, x, y)
            line.setPen(QPen(QColor("#274b70"), 1.5, Qt.PenStyle.DashLine))
            self.scene.addItem(line)
            node = QGraphicsEllipseItem(x - 25, y - 25, 50, 50)
            node.setBrush(QColor("#32205b"))
            node.setPen(QPen(QColor("#a978ff"), 2))
            details = f"{device.custom_name or device.hostname or 'Thiết bị'} · IP {device.ip_address} · MAC {device.mac_address} · {device.source}"
            node.setToolTip(details)
            node.setData(0, details)
            node.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self.scene.addItem(node)
            label = self.scene.addText(device.custom_name or device.hostname or device.ip_address)
            label.setDefaultTextColor(QColor("#d9e6ff"))
            label.setPos(x - 48, y + 28)
        self.scene.setSceneRect(20, 20, 680, 460)

    def _selection_changed(self) -> None:
        selected = self.scene.selectedItems()
        self.detail.setText(
            str(selected[0].data(0))
            if selected and selected[0].data(0)
            else "Chọn một thiết bị để xem IP, MAC và nguồn phát hiện."
        )


class MainWindow(QMainWindow):
    def __init__(
        self,
        repository: Repository | None = None,
        settings_store: SettingsStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("WiFi Guardian — Smart Router Manager")
        self.resize(1240, 760)
        self.setMinimumSize(1000, 650)
        self.setStyleSheet(THEME)
        self.repository = repository or Repository()
        self.settings_store = settings_store or SettingsStore()
        self.user_settings = self.settings_store.load()
        self.repository.prune_traffic(self.user_settings.retention_days)
        self.traffic_meter = TrafficMeter()
        self.download_history: deque[float] = deque(maxlen=CONFIG.history_limit)
        self.upload_history: deque[float] = deque(maxlen=CONFIG.history_limit)
        self._last_ping: PingResult | None = None
        self._last_reachable: bool | None = None
        self._last_latency_alert_at = 0.0
        self._last_sample_saved_at = 0.0
        self._latest_download = 0.0
        self._latest_upload = 0.0
        self._ping_busy = False
        self._scan_thread: QThread | None = None
        self._ping_thread: QThread | None = None
        self._system_thread: QThread | None = None
        self._router_thread: QThread | None = None
        self._ping_worker: PingWorker | None = None
        self._scan_worker: ScanWorker | None = None
        self._system_worker: SystemInfoWorker | None = None
        self._router_worker: RouterDetectWorker | None = None

        content = QWidget()
        self.setCentralWidget(content)
        horizontal = QHBoxLayout(content)
        horizontal.setContentsMargins(0, 0, 0, 0)
        horizontal.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(225)
        side_layout = QVBoxLayout(sidebar)
        brand = QLabel("◈ WiFi Guardian")
        brand.setObjectName("Brand")
        side_layout.addWidget(brand)

        self.stack = QStackedWidget()
        self.dashboard = DashboardPage()
        self.devices = DevicesPage(self.repository)
        self.router = RouterPage(self.repository)
        self.wifi = WifiInfoPage()
        self.topology = TopologyPage(self.repository)
        self.analytics = TrafficAnalyticsPage(self.repository)
        self.automation = AutomationPage(self.repository, self.user_settings)
        self.security = SecurityPage(self.repository)
        self.settings = SettingsPage(self.user_settings)
        pages = [
            ("Tổng quan", self.dashboard),
            ("Thiết bị đã phát hiện", self.devices),
            ("Quản lý router", self.router),
            ("Thông tin Wi‑Fi", self.wifi),
            ("Sơ đồ mạng", self.topology),
            ("Lịch sử lưu lượng", self.analytics),
            ("Cảnh báo", self.automation),
            ("Nhật ký an toàn", self.security),
            ("Cài đặt", self.settings),
        ]
        self.nav_buttons: list[QPushButton] = []
        for index, (label, page) in enumerate(pages):
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self.select_page(i))
            side_layout.addWidget(button)
            self.nav_buttons.append(button)
            self.stack.addWidget(page)
        side_layout.addStretch()
        version = QLabel("v1.1 · chạy cục bộ")
        version.setObjectName("Muted")
        side_layout.addWidget(version)
        horizontal.addWidget(sidebar)
        horizontal.addWidget(self.stack, 1)
        self.select_page(0)

        self.devices.scan_requested.connect(self.start_scan)
        self.router.detect_requested.connect(self.start_router_detect)
        self.wifi.refresh_requested.connect(self.start_system_info)
        self.settings.settings_changed.connect(self.apply_settings)
        self.automation.settings_changed.connect(self.apply_settings)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_metrics)
        self.timer.start(self.user_settings.refresh_seconds * 1000)
        QTimer.singleShot(0, self.start_system_info)
        QTimer.singleShot(150, self.refresh_metrics)

    def select_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)
        if index == 3:
            self.start_system_info()
        elif index == 4:
            self.topology.reload()
        elif index == 5:
            self.analytics.reload()
        elif index == 6:
            self.automation.reload()
        elif index == 7:
            self.security.reload()

    def apply_settings(self, settings: UserSettings) -> None:
        self.user_settings = settings
        self.settings.settings = settings
        self.automation.settings = settings
        self.settings_store.save(settings)
        self.timer.setInterval(settings.refresh_seconds * 1000)
        removed = self.repository.prune_traffic(settings.retention_days)
        self.statusBar().showMessage(
            f"Đã lưu cài đặt; chu kỳ {settings.refresh_seconds} giây"
            + (f", đã xóa {removed} mẫu cũ" if removed else ""),
            4000,
        )

    def start_system_info(self) -> None:
        if self._system_thread and self._system_thread.isRunning():
            return
        thread = QThread(self)
        worker = SystemInfoWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._system_info_complete)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._system_thread_finished)
        self._system_thread = thread
        self._system_worker = worker
        thread.start()

    def _system_info_complete(self, result: object) -> None:
        wifi, interface, gateway, dns = result
        self.dashboard.set_network_info(wifi, interface, gateway, dns)
        self.wifi.set_data(wifi, interface, gateway, dns)
        self.router.set_gateway(gateway)
        if interface:
            self.traffic_meter.set_interface(interface.name)

    def _system_thread_finished(self) -> None:
        self._system_thread = None
        self._system_worker = None

    def start_router_detect(self, host: str) -> None:
        if self._router_thread and self._router_thread.isRunning():
            return
        thread = QThread(self)
        worker = RouterDetectWorker(host)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.router.set_detect_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._router_thread_finished)
        self._router_thread = thread
        self._router_worker = worker
        thread.start()

    def _router_thread_finished(self) -> None:
        self._router_thread = None
        self._router_worker = None

    def refresh_metrics(self) -> None:
        download, upload = self.traffic_meter.sample()
        self._latest_download, self._latest_upload = download, upload
        self.download_history.append(download)
        self.upload_history.append(upload)
        self.dashboard.download.value.setText(human_rate(download))
        self.dashboard.upload.value.setText(human_rate(upload))
        self.dashboard.download_curve.setData(list(self.download_history))
        self.dashboard.upload_curve.setData(list(self.upload_history))
        if self._last_ping:
            self._update_ping_display(self._last_ping)
        else:
            self.dashboard.latency.value.setText("Đang đo…")
            self.dashboard.status.value.setText("Đang kiểm tra")
        now = time.monotonic()
        if now - self._last_sample_saved_at >= 10:
            self.repository.add_sample(
                download,
                upload,
                self._last_ping.latency_ms if self._last_ping else None,
                self._last_ping.packet_loss if self._last_ping else None,
            )
            self._last_sample_saved_at = now
        if not self._ping_busy:
            self.start_ping()

    def start_ping(self) -> None:
        self._ping_busy = True
        thread = QThread(self)
        worker = PingWorker(self.user_settings.ping_host, self.user_settings.ping_timeout_ms)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ping)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._ping_thread_finished)
        self._ping_thread = thread
        self._ping_worker = worker
        thread.start()

    def _on_ping(self, result: PingResult) -> None:
        self._last_ping = result
        self._update_ping_display(result)
        reachable = bool(result.reachable)
        if self.user_settings.alert_outage and self._last_reachable is not None:
            if self._last_reachable and not reachable:
                self._record_alert(
                    "ping_unavailable",
                    "warning",
                    f"{self.user_settings.ping_host} không phản hồi ICMP; chưa đủ để kết luận mất Internet.",
                )
            elif not self._last_reachable and reachable:
                self._record_alert(
                    "ping_restored",
                    "info",
                    f"{self.user_settings.ping_host} đã phản hồi ICMP trở lại.",
                )
        self._last_reachable = reachable
        latency = result.latency_ms
        now = time.monotonic()
        if (
            self.user_settings.alert_high_latency
            and latency is not None
            and latency >= self.user_settings.latency_threshold_ms
            and now - self._last_latency_alert_at >= 300
        ):
            self._last_latency_alert_at = now
            self._record_alert(
                "high_latency",
                "warning",
                f"Độ trễ {latency:.0f} ms vượt ngưỡng {self.user_settings.latency_threshold_ms} ms.",
            )

    def _update_ping_display(self, result: PingResult) -> None:
        latency = result.latency_ms
        jitter = result.jitter_ms
        latency_text = f"{latency:.0f} ms" if latency is not None else "Không đo được"
        if jitter is not None:
            latency_text += f" · ±{jitter:.0f}"
        self.dashboard.latency.value.setText(latency_text)
        self.dashboard.status.value.setText(
            "Có phản hồi" if result.reachable else "ICMP không phản hồi"
        )

    def _ping_thread_finished(self) -> None:
        self._ping_busy = False
        self._ping_thread = None
        self._ping_worker = None

    def _record_alert(self, kind: str, severity: str, message: str) -> None:
        self.repository.alert(kind, severity, message)
        self.statusBar().showMessage(message, 8000)
        self.automation.reload()
        self.security.reload()

    def start_scan(self) -> None:
        answer = QMessageBox.question(
            self,
            "Xác nhận quét LAN",
            "Gửi một gói ping đến từng địa chỉ trong dải LAN hiện tại rồi đọc bảng ARP của Windows? Không quét Internet công cộng.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._scan_thread and self._scan_thread.isRunning():
            return
        self.devices.scan.setEnabled(False)
        self.devices.scan.setText("Đang quét…")
        thread = QThread(self)
        worker = ScanWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._scan_complete)
        worker.failed.connect(self._scan_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._scan_thread_finished)
        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()

    def _scan_complete(self, results: object) -> None:
        new_count = 0
        for item in results:
            new_count += int(
                self.repository.upsert_device(item.ip, item.mac, item.hostname, item.source)
            )
        self.repository.audit("lan_scan", "local_private_network", "ok", f"found={len(results)} new={new_count}")
        if new_count and self.user_settings.alert_new_device:
            self._record_alert(
                "new_devices",
                "info",
                f"Phát hiện {new_count} thiết bị LAN mới trong lần quét.",
            )
        self.devices.reload()
        self.topology.reload()
        QMessageBox.information(self, "Quét hoàn tất", f"Tìm thấy {len(results)} thiết bị, trong đó {new_count} thiết bị mới.")

    def _scan_failed(self, message: str) -> None:
        self.repository.audit("lan_scan", "local_private_network", "error", message[:400])
        QMessageBox.warning(self, "Không thể quét", message)

    def _scan_thread_finished(self) -> None:
        self.devices.scan.setEnabled(True)
        self.devices.scan.setText("Quét mạng LAN")
        self._scan_thread = None
        self._scan_worker = None

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.timer.stop()
        running = [
            thread
            for thread in (
                self._ping_thread,
                self._scan_thread,
                self._system_thread,
                self._router_thread,
            )
            if thread and thread.isRunning()
        ]
        if running:
            answer = QMessageBox.question(
                self,
                "Tác vụ đang chạy",
                "Một tác vụ mạng chưa kết thúc. Chờ tác vụ hoàn tất rồi đóng ứng dụng?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                self.timer.start()
                return
            for thread in running:
                thread.quit()
                thread.wait(4000)
            if any(thread.isRunning() for thread in running):
                self.statusBar().showMessage("Đang chờ tác vụ mạng kết thúc; hãy đóng lại sau vài giây.", 4000)
                event.ignore()
                self.timer.start()
                return
        event.accept()

