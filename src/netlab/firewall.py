"""Cross-group routing setup via platform-aware sysctl management."""
import logging
from dataclasses import dataclass

from .platform import PlatformAdapter, detect_platform
from .topology import LabTopology

logger = logging.getLogger(__name__)

SYSCTL_KEY = "net.bridge.bridge-nf-call-iptables"
SYSCTL_KEY6 = "net.bridge.bridge-nf-call-ip6tables"


@dataclass(frozen=True)
class FirewallState:
    value: str
    needs_change: bool
    can_change: bool
    hint: str


class FirewallManager:
    """Manage br_netfilter via the platform adapter."""

    def __init__(
        self,
        topology: LabTopology,
        adapter: PlatformAdapter | None = None,
    ) -> None:
        self.topology = topology
        self.adapter = adapter or detect_platform()

    def has_routers(self) -> bool:
        return any(len(r.connects) >= 2 for r in self.topology.routers)

    def state(self) -> FirewallState:
        value = self.adapter.read_sysctl(SYSCTL_KEY) or "unknown"
        needs_change = (value == "1") and self.has_routers()
        admin = self.adapter.admin_status()
        persist = " ; ".join(self.persist_commands()) or ""
        hint = f"To persist: {persist}" if needs_change else ""
        return FirewallState(
            value=value,
            needs_change=needs_change,
            can_change=admin.is_admin or admin.can_elevate,
            hint=hint,
        )

    def install(self) -> FirewallState:
        state = self.state()
        if not state.needs_change:
            return state
        if not state.can_change:
            return state
        self.adapter.apply_sysctl(SYSCTL_KEY, "0")
        self.adapter.apply_sysctl(SYSCTL_KEY6, "0")
        return self.state()

    def uninstall(self) -> FirewallState:
        state = self.state()
        if state.value != "0" or not state.can_change:
            return state
        self.adapter.apply_sysctl(SYSCTL_KEY, "1")
        self.adapter.apply_sysctl(SYSCTL_KEY6, "1")
        return self.state()

    def persist_commands(self) -> list[str]:
        if not self.has_routers():
            return []
        return (
            self.adapter.persist_commands(SYSCTL_KEY, "0")
            + self.adapter.persist_commands(SYSCTL_KEY6, "0")
        )