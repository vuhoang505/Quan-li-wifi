from __future__ import annotations

import ipaddress
import platform
import re
import socket
import statistics
import subprocess
import time
from dataclasses import dataclass

import psutil


@dataclass(slots=True)
class InterfaceInfo:
    name: str
    ipv4: str | None
    ipv6: str | None
    netmask: str | None
    is_up: bool
    speed_mbps: int


@dataclass(slots=True)
class PingResult:
    host: str
    latency_ms: float | None
    packet_loss: float
    reachable: bool
    jitter_ms: float | None = None


@dataclass(slots=True)
class RouteInfo:
    gateway: str
    interface_ip: str
    metric: int


@dataclass(slots=True)
class WifiInfo:
    available: bool = False
    state: str | None = None
    ssid: str | None = None
    bssid: str | None = None
    signal: str | None = None
    radio_type: str | None = None
    channel: str | None = None
    authentication: str | None = None
    cipher: str | None = None
    receive_rate_mbps: str | None = None
    transmit_rate_mbps: str | None = None
    error: str | None = None


def active_interfaces() -> list[InterfaceInfo]:
    addresses = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    result: list[InterfaceInfo] = []
    for name, stat in stats.items():
        if not stat.isup:
            continue
        ipv4 = ipv6 = netmask = None
        for address in addresses.get(name, []):
            if address.family == socket.AF_INET and not address.address.startswith("127."):
                ipv4, netmask = address.address, address.netmask
            elif address.family == socket.AF_INET6 and not address.address.startswith("::1"):
                ipv6 = address.address.split("%", 1)[0]
        if ipv4 or ipv6:
            result.append(InterfaceInfo(name, ipv4, ipv6, netmask, True, stat.speed))
    return result


def parse_default_routes(output: str) -> list[RouteInfo]:
    routes: list[RouteInfo] = []
    pattern = re.compile(
        r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+"
        r"(\d{1,3}(?:\.\d{1,3}){3})\s+"
        r"(\d{1,3}(?:\.\d{1,3}){3})\s+(\d+)\s*$",
        re.MULTILINE,
    )
    for gateway, interface_ip, metric in pattern.findall(output):
        try:
            ipaddress.ip_address(gateway)
            ipaddress.ip_address(interface_ip)
            routes.append(RouteInfo(gateway, interface_ip, int(metric)))
        except ValueError:
            continue
    return routes


def default_route() -> RouteInfo | None:
    if platform.system() != "Windows":
        return None
    try:
        proc = subprocess.run(
            ["route", "print", "-4", "0.0.0.0"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    routes = parse_default_routes(proc.stdout)
    if not routes:
        return None
    interfaces_by_ip = {
        item.ipv4: item.name.casefold() for item in active_interfaces() if item.ipv4
    }
    virtual_words = ("virtual", "vpn", "vmware", "vbox", "radmin", "loopback")
    physical_routes = [
        route
        for route in routes
        if not any(
            word in interfaces_by_ip.get(route.interface_ip, "") for word in virtual_words
        )
    ]
    candidates = physical_routes or routes
    private_routes = [
        route for route in candidates if ipaddress.ip_address(route.gateway).is_private
    ]
    return min(private_routes or candidates, key=lambda route: route.metric)


def primary_interface() -> InterfaceInfo | None:
    route = default_route()
    interfaces = active_interfaces()
    if route:
        for interface in interfaces:
            if interface.ipv4 == route.interface_ip:
                return interface
    private_interfaces: list[InterfaceInfo] = []
    for interface in interfaces:
        if not interface.ipv4:
            continue
        try:
            if ipaddress.ip_address(interface.ipv4).is_private:
                private_interfaces.append(interface)
        except ValueError:
            continue
    virtual_words = ("virtual", "vpn", "vmware", "vbox", "radmin", "loopback")
    physical = [
        item for item in private_interfaces if not any(word in item.name.casefold() for word in virtual_words)
    ]
    return (physical or private_interfaces or interfaces or [None])[0]


def primary_network() -> ipaddress.IPv4Network | None:
    item = primary_interface()
    if item and item.ipv4 and item.netmask:
        try:
            network = ipaddress.ip_network(f"{item.ipv4}/{item.netmask}", strict=False)
            if network.is_private and network.prefixlen >= 16:
                return network
        except ValueError:
            pass
    return None


def default_gateway() -> str | None:
    route = default_route()
    return route.gateway if route else None


def parse_wifi_info(output: str, return_code: int = 0) -> WifiInfo:
    lowered = output.casefold()
    if return_code != 0 or "returns error" in lowered or "access is denied" in lowered:
        message = "Không đọc được thông tin Wi‑Fi."
        if "requires elevation" in lowered or "access" in lowered:
            message += " Hãy mở terminal bằng quyền Administrator nếu muốn xem chi tiết Wi‑Fi."
        return WifiInfo(error=message)
    values: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip().casefold()] = value.strip()
    aliases = {
        "state": ("state", "trạng thái"),
        "ssid": ("ssid",),
        "bssid": ("bssid",),
        "signal": ("signal", "tín hiệu"),
        "radio": ("radio type", "loại radio"),
        "channel": ("channel", "kênh"),
        "auth": ("authentication", "xác thực"),
        "cipher": ("cipher", "mã hóa"),
        "rx": ("receive rate (mbps)",),
        "tx": ("transmit rate (mbps)",),
    }

    def find(name: str) -> str | None:
        for key in aliases[name]:
            if key in values:
                return values[key]
        return None

    ssid = find("ssid")
    return WifiInfo(
        available=bool(ssid),
        state=find("state"),
        ssid=ssid,
        bssid=find("bssid"),
        signal=find("signal"),
        radio_type=find("radio"),
        channel=find("channel"),
        authentication=find("auth"),
        cipher=find("cipher"),
        receive_rate_mbps=find("rx"),
        transmit_rate_mbps=find("tx"),
        error=None if ssid else "Không có kết nối Wi‑Fi đang hoạt động.",
    )


def wifi_info() -> WifiInfo:
    if platform.system() != "Windows":
        return WifiInfo(error="Thông tin Wi‑Fi chi tiết hiện chỉ hỗ trợ Windows.")
    try:
        proc = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return WifiInfo(error="Lệnh đọc Wi‑Fi không phản hồi.")
    return parse_wifi_info(proc.stdout + proc.stderr, proc.returncode)


def current_ssid() -> str | None:
    return wifi_info().ssid


def parse_dns_servers(output: str, interface_ip: str | None) -> list[str]:
    if not interface_ip:
        return []
    blocks = re.split(r"\r?\n\s*\r?\n", output)
    block = next((item for item in blocks if interface_ip in item), "")
    if not block:
        return []
    servers: list[str] = []
    collecting = False
    for line in block.splitlines():
        if re.search(r"DNS Servers?\s*[^:]*:", line, re.IGNORECASE):
            collecting = True
            candidate = line.split(":", 1)[1].strip()
        elif collecting and line[:1].isspace() and ":" not in line.strip().rstrip(":" ):
            candidate = line.strip()
        elif collecting and re.fullmatch(r"[0-9a-fA-F:.%]+", line.strip()):
            candidate = line.strip()
        else:
            if collecting:
                break
            continue
        token = candidate.split()[0] if candidate else ""
        try:
            ipaddress.ip_address(token.split("%", 1)[0])
        except ValueError:
            continue
        if token not in servers:
            servers.append(token)
    return servers


def dns_servers() -> list[str]:
    if platform.system() != "Windows":
        return []
    interface = primary_interface()
    try:
        proc = subprocess.run(
            ["ipconfig", "/all"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_dns_servers(proc.stdout, interface.ipv4 if interface else None)


def ping(host: str, timeout_ms: int = 1200, count: int = 2) -> PingResult:
    flag = "-n" if platform.system() == "Windows" else "-c"
    timeout_flag = "-w" if platform.system() == "Windows" else "-W"
    timeout_value = str(timeout_ms if platform.system() == "Windows" else max(1, timeout_ms // 1000))
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["ping", flag, str(count), timeout_flag, timeout_value, host],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=max(3, count * timeout_ms / 1000 + 2),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return PingResult(host, None, 100.0, False, None)
    elapsed = (time.monotonic() - started) * 1000 / max(count, 1)
    combined = proc.stdout + proc.stderr
    times = re.findall(r"(?:time[=<]|thời gian[=<])\s*(\d+(?:\.\d+)?)\s*ms", combined, re.I)
    loss_match = re.search(r"(\d+(?:\.\d+)?)%\s*(?:loss|mất)", combined, re.I)
    loss = float(loss_match.group(1)) if loss_match else (0.0 if proc.returncode == 0 else 100.0)
    latency = sum(map(float, times)) / len(times) if times else (elapsed if proc.returncode == 0 else None)
    numeric_times = list(map(float, times))
    jitter = statistics.pstdev(numeric_times) if len(numeric_times) > 1 else (0.0 if numeric_times else None)
    return PingResult(host, latency, loss, proc.returncode == 0, jitter)


class TrafficMeter:
    def __init__(self, interface_name: str | None = None) -> None:
        self.interface_name = interface_name or ""
        counters = self._counters()
        self._sent = counters.bytes_sent
        self._recv = counters.bytes_recv
        self._at = time.monotonic()

    def _counters(self):  # type: ignore[no-untyped-def]
        per_interface = psutil.net_io_counters(pernic=True)
        if self.interface_name in per_interface:
            return per_interface[self.interface_name]
        return psutil.net_io_counters()

    def set_interface(self, interface_name: str) -> None:
        if interface_name == self.interface_name:
            return
        self.interface_name = interface_name
        counters = self._counters()
        self._sent = counters.bytes_sent
        self._recv = counters.bytes_recv
        self._at = time.monotonic()

    def sample(self) -> tuple[float, float]:
        counters = self._counters()
        now = time.monotonic()
        elapsed = max(now - self._at, 0.001)
        download = max(0, counters.bytes_recv - self._recv) / elapsed
        upload = max(0, counters.bytes_sent - self._sent) / elapsed
        self._sent, self._recv, self._at = counters.bytes_sent, counters.bytes_recv, now
        return download, upload

