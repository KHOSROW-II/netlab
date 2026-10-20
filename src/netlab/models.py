"""Data models used across the platform."""
from dataclasses import dataclass, field
from ipaddress import IPv4Network


@dataclass(frozen=True)
class NetworkConfig:
    """Immutable description of a lab network."""

    name: str
    subnet: IPv4Network
    gateway_offset: int = 1

    @property
    def gateway(self) -> str:
        return str(self.subnet.network_address + self.gateway_offset)


@dataclass
class Host:
    """A simulated host backed by a Docker container."""

    name: str
    ip: str
    container_id: str = ""
    image: str = ""
    networks: dict[str, str] = field(default_factory=dict)