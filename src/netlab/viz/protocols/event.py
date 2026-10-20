"""Protocol event model."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProtocolEvent:
    """A single protocol step produced by simulation or live capture."""

    step: int
    layer: str        # L2, L3, L4, L7
    protocol: str     # ARP, ICMP, DNS, DHCP
    src: str
    dst: str
    info: str
    at_node: str = ""