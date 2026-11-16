from __future__ import annotations

import ipaddress
import platform
import re
import socket
import subprocess
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, wait

from .network import primary_network


@dataclass(slots=True)
class DiscoveredDevice:
    ip: str
    mac: str
    hostname: str | None
    source: str = "LAN/ARP"


def _hostname(ip: str) -> str | None:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, TimeoutError):
        return None


def parse_arp_table(output: str, network: ipaddress.IPv4Network) -> list[tuple[str, str]]:
    found: dict[str, str] = {}
    pattern = re.compile(
        r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+"
        r"([0-9a-f]{2}(?:[-:][0-9a-f]{2}){5})\s+",
        re.IGNORECASE | re.MULTILINE,
    )
    for ip_text, mac_text in pattern.findall(output):
        try:
            address = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        normalized_mac = mac_text.replace("-", ":").upper()
        if (
            address not in network
            or address in (network.network_address, network.broadcast_address)
            or address.is_multicast
            or normalized_mac in {"00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"}
        ):
            continue
        found[str(address)] = normalized_mac
    return sorted(found.items(), key=lambda item: ipaddress.ip_address(item[0]))


def _resolve_names(raw: list[tuple[str, str]], source: str) -> list[DiscoveredDevice]:
    names: dict[str, str | None] = {}
    pool = ThreadPoolExecutor(max_workers=12)
    futures = {pool.submit(_hostname, ip): ip for ip, _ in raw}
    done, _ = wait(futures, timeout=2.5)
    for future in done:
        try:
            names[futures[future]] = future.result()
        except OSError:
            names[futures[future]] = None
    pool.shutdown(wait=False, cancel_futures=True)
    return [DiscoveredDevice(ip, mac, names.get(ip), source) for ip, mac in raw]


def _ping_once(ip: str) -> None:
    timeout_flag = "-w" if platform.system() == "Windows" else "-W"
    timeout_value = "250" if platform.system() == "Windows" else "1"
    count_flag = "-n" if platform.system() == "Windows" else "-c"
    try:
        subprocess.run(
            ["ping", count_flag, "1", timeout_flag, timeout_value, ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def _windows_arp_scan(network: ipaddress.IPv4Network) -> list[tuple[str, str]]:
    hosts = [str(address) for address in network.hosts()]
    with ThreadPoolExecutor(max_workers=min(48, len(hosts) or 1)) as pool:
        list(pool.map(_ping_once, hosts))
    try:
        proc = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Không thể đọc bảng ARP của Windows.") from exc
    return parse_arp_table(proc.stdout, network)


def scan_lan() -> list[DiscoveredDevice]:
    """Quét đúng LAN riêng hiện tại bằng ping + bảng ARP tích hợp của Windows."""
    network = primary_network()
    if network is None or not network.is_private:
        raise RuntimeError("Không xác định được mạng LAN riêng đang hoạt động.")
    if network.num_addresses > 1024:
        raise RuntimeError("Dải mạng quá lớn; chỉ hỗ trợ quét tối đa 1024 địa chỉ.")
    raw = _windows_arp_scan(network)
    return _resolve_names(raw, "LAN/Windows ARP")


def is_safe_lan_target(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        network = primary_network()
        return bool(network and address in network and address.is_private)
    except ValueError:
        return False

