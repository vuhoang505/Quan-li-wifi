from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class RouterCapabilities:
    read_status: bool = False
    list_clients: bool = False
    read_wifi: bool = False
    write_wifi: bool = False
    access_control: bool = False
    guest_network: bool = False
    reason: str = "Chưa xác minh model, firmware và API tương thích."


@dataclass(slots=True)
class RouterInfo:
    host: str
    vendor: str = "Không xác định"
    model: str = "Không xác định"
    firmware: str = "Không xác định"
    management_url: str | None = None
    capabilities: RouterCapabilities = field(default_factory=RouterCapabilities)


class RouterAdapter(ABC):
    def __init__(self, host: str) -> None:
        self.host = host

    @abstractmethod
    def detect(self) -> bool: ...

    @abstractmethod
    def get_router_info(self) -> RouterInfo: ...

    @abstractmethod
    def get_router_status(self) -> dict[str, object]: ...

    @abstractmethod
    def get_capabilities(self) -> RouterCapabilities: ...

    @abstractmethod
    def disconnect(self) -> None: ...

