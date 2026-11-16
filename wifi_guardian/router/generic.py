from __future__ import annotations

import ipaddress
import socket

from ..core.network import default_gateway, primary_network
from .base import RouterAdapter, RouterCapabilities, RouterInfo


class GenericRouterAdapter(RouterAdapter):
    """Adapter chỉ đọc. Không đoán endpoint và không gửi thông tin xác thực."""

    def __init__(self, host: str) -> None:
        super().__init__(host)
        self._capabilities = RouterCapabilities(
            reason="Router phổ thông: chỉ phát hiện địa chỉ và mở giao diện quản trị chính thức."
        )
        self.detected_url: str | None = None

    def _is_safe_target(self) -> bool:
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError:
            return False
        if address.is_loopback or address.is_link_local or address.is_multicast:
            return False
        network = primary_network()
        gateway = default_gateway()
        return bool(
            address.is_private
            and ((network is not None and address in network) or self.host == gateway)
        )

    def detect(self) -> bool:
        self.detected_url = None
        if not self._is_safe_target():
            return False
        for port, scheme in ((443, "https"), (80, "http")):
            try:
                with socket.create_connection((self.host, port), timeout=0.6):
                    self.detected_url = f"{scheme}://{self.host}"
                    return True
            except OSError:
                continue
        return False

    def get_router_info(self) -> RouterInfo:
        return RouterInfo(
            host=self.host,
            management_url=self.detected_url,
            capabilities=self._capabilities,
        )

    def get_router_status(self) -> dict[str, object]:
        return {"reachable": self.detect()}

    def get_capabilities(self) -> RouterCapabilities:
        return self._capabilities

    def disconnect(self) -> None:
        return None

