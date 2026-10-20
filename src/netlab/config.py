"""High-level lab configuration."""
from dataclasses import dataclass


@dataclass
class LabConfig:
    """User-provided parameters for a lab deployment."""
    host_count: int = 5
    subnet: str = "10.10.0.0/24"
    network_name: str = "netlab-p1"
    image: str = "nicolaka/netshoot:latest"
    start_ip_offset: int = 10
    label: str = "netlab.phase1"