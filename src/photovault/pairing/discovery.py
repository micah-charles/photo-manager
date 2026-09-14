"""mDNS/DNS-SD discovery for Android Companion devices.

Only public metadata is advertised.  Tokens and private credentials never
enter TXT records.  The dependency is optional so legacy/manual mode remains
usable on machines without multicast DNS support.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Callable

SERVICE_TYPE = "_photovault._tcp.local."


@dataclass(frozen=True)
class DiscoveredAndroid:
    device_id: str
    display_name: str
    host: str
    port: int
    protocol: str = "1"
    api_version: str = "2"
    pairing: bool = True
    public_key_fingerprint: str | None = None


class AndroidDiscoveryService:
    def __init__(self, on_change: Callable[[str, DiscoveredAndroid], None] | None = None) -> None:
        self.on_change = on_change
        self._devices: dict[str, DiscoveredAndroid] = {}
        self._service_devices: dict[str, str] = {}
        self._lock = RLock()
        self._browser = None
        self._zeroconf = None

    @property
    def devices(self) -> list[DiscoveredAndroid]:
        with self._lock: return list(self._devices.values())

    def start(self) -> bool:
        try:
            from zeroconf import ServiceBrowser, Zeroconf
        except ImportError: return False
        service = self
        class Listener:
            def add_service(self, zc, service_type, name): service._resolve(zc, service_type, name, "appeared")
            def update_service(self, zc, service_type, name): service._resolve(zc, service_type, name, "updated")
            def remove_service(self, zc, service_type, name): service._remove(name)
        self._zeroconf = Zeroconf()
        self._browser = ServiceBrowser(self._zeroconf, SERVICE_TYPE, Listener())
        return True

    def stop(self) -> None:
        if self._zeroconf is not None: self._zeroconf.close()
        self._zeroconf = self._browser = None

    def _resolve(self, zc, service_type: str, name: str, change: str) -> None:
        info = zc.get_service_info(service_type, name, timeout=1500)
        if info is None: return
        props = {bytes(k).decode(errors="ignore"): bytes(v).decode(errors="ignore") for k, v in info.properties.items()}
        device_id, display_name = props.get("device_id"), props.get("device_name", name.split(".")[0])
        if not device_id: return
        host = info.parsed_addresses()[0] if info.parsed_addresses() else info.server
        device = DiscoveredAndroid(device_id, display_name, host, info.port, props.get("protocol", "1"), props.get("api_version", "2"), props.get("pairing", "yes") == "yes", props.get("public_key_fingerprint"))
        with self._lock:
            self._devices[device_id] = device
            self._service_devices[name] = device_id
        if self.on_change: self.on_change(change, device)

    def _remove(self, name: str) -> None:
        with self._lock:
            device_id = self._service_devices.pop(name, None)
            device = self._devices.pop(device_id, None) if device_id else None
        if device and self.on_change: self.on_change("disappeared", device)
