from __future__ import annotations

import re
import csv
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.network import InterfaceInfo, WifiInfo
from ..database import Repository
from .settings_store import UserSettings


def _header(heading: str, description: str) -> QVBoxLayout:
    layout = QVBoxLayout()
    title = QLabel(heading)
    title.setObjectName("PageTitle")
    subtitle = QLabel(description)
    subtitle.setObjectName("Muted")
    subtitle.setWordWrap(True)
    layout.addWidget(title)
    layout.addWidget(subtitle)
    return layout


def _local_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%d/%m/%Y %H:%M:%S")


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _rate(value: float) -> str:
    units = ("B/s", "KB/s", "MB/s", "GB/s")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.1f} {units[index]}"


class WifiInfoPage(QWidget):
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.addLayout(
            _header(
                "Thông tin Wi‑Fi",
                "Dữ liệu chỉ đọc từ Windows. Trang này không thay đổi SSID, mật khẩu hoặc cấu hình router.",
            )
        )
        card = QFrame()
        card.setObjectName("Card")
        form = QFormLayout(card)
        self.values: dict[str, QLabel] = {}
        fields = (
            ("adapter", "Adapter"),
            ("address", "Địa chỉ máy"),
            ("gateway", "Gateway"),
            ("dns", "DNS"),
            ("state", "Trạng thái"),
            ("ssid", "SSID"),
            ("bssid", "BSSID"),
            ("signal", "Tín hiệu"),
            ("radio", "Chuẩn radio"),
            ("channel", "Kênh"),
            ("auth", "Xác thực"),
            ("cipher", "Mã hóa"),
            ("rates", "Tốc độ liên kết Rx / Tx"),
        )
        for key, caption in fields:
            label = QLabel("Đang đọc…")
            label.setTextInteractionFlags(
                label.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self.values[key] = label
            form.addRow(caption, label)
        root.addWidget(card)
        self.message = QLabel("")
        self.message.setObjectName("Muted")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        refresh = QPushButton("Đọc lại thông tin")
        refresh.setObjectName("Primary")
        refresh.clicked.connect(self.refresh_requested)
        root.addWidget(refresh)
        root.addStretch()

    def set_data(
        self,
        info: WifiInfo,
        interface: InterfaceInfo | None,
        gateway: str | None,
        dns: list[str],
    ) -> None:
        self.values["adapter"].setText(interface.name if interface else "Không xác định")
        address = " / ".join(filter(None, (interface.ipv4, interface.ipv6))) if interface else ""
        self.values["address"].setText(address or "Không khả dụng")
        self.values["gateway"].setText(gateway or "Không xác định")
        self.values["dns"].setText(", ".join(dns) if dns else "Không xác định")
        self.values["state"].setText(info.state or "Không khả dụng")
        self.values["ssid"].setText(info.ssid or "Không khả dụng")
        self.values["bssid"].setText(info.bssid or "Không khả dụng")
        self.values["signal"].setText(info.signal or "Không khả dụng")
        self.values["radio"].setText(info.radio_type or "Không khả dụng")
        self.values["channel"].setText(info.channel or "Không khả dụng")
        self.values["auth"].setText(info.authentication or "Không khả dụng")
        self.values["cipher"].setText(info.cipher or "Không khả dụng")
        rates = " / ".join(filter(None, (info.receive_rate_mbps, info.transmit_rate_mbps)))
        self.values["rates"].setText(f"{rates} Mbps" if rates else "Không khả dụng")
        self.message.setText(info.error or "Dữ liệu được đọc trực tiếp từ netsh của Windows.")


class TrafficAnalyticsPage(QWidget):
    def __init__(self, repository: Repository) -> None:
        super().__init__()
        self.repository = repository
        root = QVBoxLayout(self)
        root.addLayout(
            _header(
                "Phân tích lưu lượng",
                "Lịch sử của adapter chính trên máy tính này; không phải tổng lưu lượng của router.",
            )
        )
        tools = QHBoxLayout()
        self.range = QComboBox()
        self.range.addItem("1 giờ", 1)
        self.range.addItem("6 giờ", 6)
        self.range.addItem("24 giờ", 24)
        self.range.addItem("7 ngày", 168)
        self.range.setCurrentIndex(2)
        refresh = QPushButton("Làm mới")
        refresh.clicked.connect(self.reload)
        export = QPushButton("Xuất CSV")
        export.clicked.connect(self.export_csv)
        self.range.currentIndexChanged.connect(self.reload)
        tools.addWidget(QLabel("Khoảng thời gian"))
        tools.addWidget(self.range)
        tools.addStretch()
        tools.addWidget(export)
        tools.addWidget(refresh)
        root.addLayout(tools)
        metrics = QHBoxLayout()
        self.average_down = QLabel("Tải xuống TB: —")
        self.maximum_down = QLabel("Cao nhất: —")
        self.average_up = QLabel("Tải lên TB: —")
        self.average_latency = QLabel("Ping TB: —")
        for label in (self.average_down, self.maximum_down, self.average_up, self.average_latency):
            card = QFrame()
            card.setObjectName("Card")
            layout = QVBoxLayout(card)
            layout.addWidget(label)
            metrics.addWidget(card)
        root.addLayout(metrics)
        axis = pg.DateAxisItem(orientation="bottom")
        self.plot = pg.PlotWidget(axisItems={"bottom": axis})
        self.plot.setBackground("#0d1629")
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setLabel("left", "Lưu lượng", units="B/s")
        self.plot.addLegend()
        self.down_curve = self.plot.plot(pen=pg.mkPen("#55e7ff", width=2), name="Download")
        self.up_curve = self.plot.plot(pen=pg.mkPen("#a978ff", width=2), name="Upload")
        root.addWidget(self.plot, 1)
        self.empty = QLabel("")
        self.empty.setObjectName("Muted")
        root.addWidget(self.empty)
        self.reload()

    def reload(self, _index: int = -1) -> None:
        hours = int(self.range.currentData())
        samples = self.repository.traffic_samples(hours=hours)
        if not samples:
            self.down_curve.setData([], [])
            self.up_curve.setData([], [])
            self.empty.setText("Chưa có mẫu trong khoảng đã chọn. Hãy để ứng dụng giám sát một lúc.")
            return
        x = [_timestamp(sample.created_at) for sample in samples]
        download = [sample.download_bps for sample in samples]
        upload = [sample.upload_bps for sample in samples]
        latencies = [sample.latency_ms for sample in samples if sample.latency_ms is not None]
        self.down_curve.setData(x, download)
        self.up_curve.setData(x, upload)
        self.average_down.setText(f"Tải xuống TB: {_rate(sum(download) / len(download))}")
        self.maximum_down.setText(f"Cao nhất: {_rate(max(download))}")
        self.average_up.setText(f"Tải lên TB: {_rate(sum(upload) / len(upload))}")
        self.average_latency.setText(
            f"Ping TB: {sum(latencies) / len(latencies):.0f} ms" if latencies else "Ping TB: Không có dữ liệu"
        )
        self.empty.setText(f"{len(samples)} mẫu được tải từ SQLite.")

    def export_csv(self) -> None:
        hours = int(self.range.currentData())
        samples = self.repository.traffic_samples(hours=hours, limit=20_000)
        if not samples:
            QMessageBox.information(self, "Không có dữ liệu", "Không có mẫu để xuất trong khoảng đã chọn.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Xuất lịch sử lưu lượng",
            f"wifi-guardian-{hours}h.csv",
            "CSV (*.csv)",
        )
        if not filename:
            return
        try:
            with Path(filename).open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["timestamp_utc", "download_Bps", "upload_Bps", "latency_ms", "packet_loss_percent"]
                )
                for sample in samples:
                    created_at = sample.created_at
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    writer.writerow(
                        [
                            created_at.astimezone(timezone.utc).isoformat(),
                            round(sample.download_bps, 2),
                            round(sample.upload_bps, 2),
                            sample.latency_ms if sample.latency_ms is not None else "",
                            sample.packet_loss if sample.packet_loss is not None else "",
                        ]
                    )
        except OSError as exc:
            QMessageBox.warning(self, "Không thể xuất", str(exc))
            return
        self.repository.audit("traffic_export", filename, "ok", f"samples={len(samples)}")
        QMessageBox.information(self, "Đã xuất", f"Đã lưu {len(samples)} mẫu vào:\n{filename}")


class AutomationPage(QWidget):
    settings_changed = Signal(object)

    def __init__(self, repository: Repository, settings: UserSettings) -> None:
        super().__init__()
        self.repository = repository
        self.settings = settings
        root = QVBoxLayout(self)
        root.addLayout(
            _header(
                "Cảnh báo tự động",
                "Cảnh báo hoạt động khi ứng dụng đang mở; không tự thay đổi router hoặc chặn thiết bị.",
            )
        )
        rules = QFrame()
        rules.setObjectName("Card")
        form = QFormLayout(rules)
        self.outage = QCheckBox("Cảnh báo khi máy chủ kiểm tra ngừng phản hồi")
        self.outage.setChecked(settings.alert_outage)
        self.latency = QCheckBox("Cảnh báo độ trễ cao")
        self.latency.setChecked(settings.alert_high_latency)
        self.new_device = QCheckBox("Cảnh báo thiết bị LAN mới")
        self.new_device.setChecked(settings.alert_new_device)
        self.threshold = QSpinBox()
        self.threshold.setRange(10, 5000)
        self.threshold.setSuffix(" ms")
        self.threshold.setValue(settings.latency_threshold_ms)
        apply_button = QPushButton("Lưu quy tắc")
        apply_button.setObjectName("Primary")
        apply_button.clicked.connect(self.apply)
        form.addRow(self.outage)
        form.addRow(self.latency)
        form.addRow("Ngưỡng độ trễ", self.threshold)
        form.addRow(self.new_device)
        form.addRow(apply_button)
        root.addWidget(rules)
        root.addWidget(QLabel("Sự kiện cảnh báo gần đây"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Thời gian", "Mức", "Loại", "Nội dung"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        self.reload()

    def apply(self) -> None:
        self.settings = replace(
            self.settings,
            alert_outage=self.outage.isChecked(),
            alert_high_latency=self.latency.isChecked(),
            alert_new_device=self.new_device.isChecked(),
            latency_threshold_ms=self.threshold.value(),
        )
        self.settings_changed.emit(self.settings)

    def reload(self) -> None:
        events = self.repository.audit_logs(limit=200, action_prefix="alert:")
        self.table.setRowCount(len(events))
        for row, event in enumerate(events):
            values = (_local_time(event.created_at), event.result, event.action.removeprefix("alert:"), event.detail or "")
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))


class SecurityPage(QWidget):
    def __init__(self, repository: Repository) -> None:
        super().__init__()
        self.repository = repository
        root = QVBoxLayout(self)
        root.addLayout(
            _header(
                "Nhật ký an toàn",
                "Các thao tác nhạy cảm và cảnh báo được lưu cục bộ; ứng dụng không thu thập mật khẩu router.",
            )
        )
        facts = QLabel(
            "✓ Chỉ quét dải LAN đang hoạt động   ·   ✓ Không có thao tác deauthentication   ·   "
            "✓ Không có chức năng đổi cấu hình router chưa xác minh"
        )
        facts.setWordWrap(True)
        facts.setObjectName("Muted")
        root.addWidget(facts)
        tools = QHBoxLayout()
        tools.addStretch()
        refresh = QPushButton("Làm mới nhật ký")
        refresh.clicked.connect(self.reload)
        tools.addWidget(refresh)
        root.addLayout(tools)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Thời gian", "Hành động", "Đối tượng", "Kết quả", "Chi tiết"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        self.reload()

    def reload(self) -> None:
        logs = self.repository.audit_logs(limit=500)
        self.table.setRowCount(len(logs))
        for row, log in enumerate(logs):
            values = (_local_time(log.created_at), log.action, log.target, log.result, log.detail or "")
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))


class SettingsPage(QWidget):
    settings_changed = Signal(object)
    HOST_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")

    def __init__(self, settings: UserSettings) -> None:
        super().__init__()
        self.settings = settings
        root = QVBoxLayout(self)
        root.addLayout(_header("Cài đặt", "Thiết lập được lưu cục bộ và áp dụng cho các lần chạy sau."))
        card = QFrame()
        card.setObjectName("Card")
        form = QFormLayout(card)
        self.interval = QSpinBox()
        self.interval.setRange(1, 60)
        self.interval.setValue(settings.refresh_seconds)
        self.interval.setSuffix(" giây")
        self.host = QLineEdit(settings.ping_host)
        self.timeout = QSpinBox()
        self.timeout.setRange(300, 5000)
        self.timeout.setSingleStep(100)
        self.timeout.setValue(settings.ping_timeout_ms)
        self.timeout.setSuffix(" ms")
        self.retention = QSpinBox()
        self.retention.setRange(1, 365)
        self.retention.setValue(settings.retention_days)
        self.retention.setSuffix(" ngày")
        save = QPushButton("Lưu cài đặt")
        save.setObjectName("Primary")
        save.clicked.connect(self.apply)
        self.message = QLabel("")
        self.message.setObjectName("Muted")
        form.addRow("Chu kỳ cập nhật", self.interval)
        form.addRow("Máy chủ ping", self.host)
        form.addRow("Timeout ping", self.timeout)
        form.addRow("Giữ lịch sử", self.retention)
        form.addRow("Khởi động cùng Windows", QLabel("Không — chỉ chạy từ terminal"))
        form.addRow(save)
        form.addRow(self.message)
        root.addWidget(card)
        root.addStretch()

    def apply(self) -> None:
        host = self.host.text().strip()
        if not self.HOST_PATTERN.fullmatch(host):
            self.message.setText("Máy chủ ping không hợp lệ.")
            return
        self.settings = replace(
            self.settings,
            refresh_seconds=self.interval.value(),
            ping_host=host,
            ping_timeout_ms=self.timeout.value(),
            retention_days=self.retention.value(),
        )
        self.message.setText("Đã lưu cài đặt.")
        self.settings_changed.emit(self.settings)

