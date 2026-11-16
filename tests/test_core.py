from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta, timezone

import wifi_guardian.router.generic as generic_module

from wifi_guardian.core.discovery import is_safe_lan_target, parse_arp_table
from wifi_guardian.core.network import (
    TrafficMeter,
    active_interfaces,
    parse_default_routes,
    parse_dns_servers,
    parse_wifi_info,
)
from wifi_guardian.database import Repository
from wifi_guardian.router import GenericRouterAdapter


def test_repository_round_trip() -> None:
    repo = Repository("sqlite:///:memory:")
    assert repo.upsert_device("192.168.1.2", "aa:bb:cc:dd:ee:ff", "phone") is True
    assert repo.upsert_device("192.168.1.3", "AA:BB:CC:DD:EE:FF", "phone-new") is False
    devices = repo.devices()
    assert len(devices) == 1
    assert devices[0].ip_address == "192.168.1.3"
    repo.rename_device("AA:BB:CC:DD:EE:FF", "Điện thoại")
    assert repo.devices()[0].custom_name == "Điện thoại"


def test_network_collectors_do_not_crash() -> None:
    assert isinstance(active_interfaces(), list)
    meter = TrafficMeter()
    download, upload = meter.sample()
    assert download >= 0
    assert upload >= 0


def test_public_address_is_never_lan_target() -> None:
    assert is_safe_lan_target("8.8.8.8") is False
    assert is_safe_lan_target("not-an-ip") is False


def test_generic_router_rejects_public_or_hostname_targets() -> None:
    assert GenericRouterAdapter("8.8.8.8").detect() is False
    assert GenericRouterAdapter("example.com").detect() is False
    assert GenericRouterAdapter("127.0.0.1").detect() is False


def test_generic_router_remembers_https_url(monkeypatch) -> None:
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(generic_module, "primary_network", lambda: ipaddress.ip_network("192.168.1.0/24"))
    monkeypatch.setattr(generic_module, "default_gateway", lambda: "192.168.1.1")
    monkeypatch.setattr(generic_module.socket, "create_connection", lambda *_args, **_kwargs: Connection())
    adapter = GenericRouterAdapter("192.168.1.1")
    assert adapter.detect() is True
    assert adapter.get_router_info().management_url == "https://192.168.1.1"


def test_default_route_parser_keeps_metric_and_interface() -> None:
    output = """
          0.0.0.0          0.0.0.0         26.0.0.1     26.167.29.64   9257
          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.98     30
    """
    routes = parse_default_routes(output)
    assert len(routes) == 2
    assert routes[1].gateway == "192.168.1.1"
    assert routes[1].interface_ip == "192.168.1.98"
    assert routes[1].metric == 30


def test_wifi_and_dns_parsers() -> None:
    output = """
        State                  : connected
        SSID                   : Home WiFi
        BSSID                  : aa:bb:cc:dd:ee:ff
        Radio type             : 802.11ax
        Authentication         : WPA2-Personal
        Cipher                 : CCMP
        Channel                : 6
        Receive rate (Mbps)    : 573
        Transmit rate (Mbps)   : 573
        Signal                 : 91%
    """
    info = parse_wifi_info(output)
    assert info.available is True
    assert info.ssid == "Home WiFi"
    assert info.bssid == "aa:bb:cc:dd:ee:ff"
    assert info.channel == "6"

    ipconfig = """
Wireless LAN adapter Wi-Fi:
   IPv4 Address. . . . . . . . . . . : 192.168.1.98(Preferred)
   DNS Servers . . . . . . . . . . . : fe80::1%20
                                       1.1.1.1

Ethernet adapter Other:
   IPv4 Address. . . . . . . . . . . : 192.168.56.1(Preferred)
   DNS Servers . . . . . . . . . . . : 8.8.8.8
    """
    assert parse_dns_servers(ipconfig, "192.168.1.98") == ["fe80::1%20", "1.1.1.1"]


def test_arp_parser_filters_other_network_and_broadcast() -> None:
    output = """
      192.168.1.1          aa-bb-cc-dd-ee-01     dynamic
      192.168.1.255        ff-ff-ff-ff-ff-ff     static
      192.168.56.2         aa-bb-cc-dd-ee-02     dynamic
    """
    network = ipaddress.ip_network("192.168.1.0/24")
    assert parse_arp_table(output, network) == [("192.168.1.1", "AA:BB:CC:DD:EE:01")]


def test_history_audit_and_retention() -> None:
    repo = Repository("sqlite:///:memory:")
    old = datetime.now(timezone.utc) - timedelta(days=5)
    repo.add_sample(1, 2, None, None, created_at=old)
    repo.add_sample(100, 50, 12, 0)
    recent = repo.traffic_samples(hours=24)
    assert len(recent) == 1
    assert recent[0].download_bps == 100
    assert repo.prune_traffic(1) == 1
    repo.alert("high_latency", "warning", "Ping cao")
    alerts = repo.audit_logs(action_prefix="alert:")
    assert len(alerts) == 1
    assert alerts[0].detail == "Ping cao"

