"""DHCP DORA simulation (no live capture in this phase)."""
from .event import ProtocolEvent
from .simulator import Simulator


class DHCPSimulator(Simulator):
    """Simulate the DHCP DORA exchange."""

    def run(self) -> list[ProtocolEvent]:
        planner = self._planner()
        pool_first = str(planner.info.network.network_address + 100)
        server_ip = planner.gateway

        self._emit("L7", "DHCP", "0.0.0.0", "255.255.255.255",
                   "DISCOVER from client (no IP yet, MAC only)")
        self._emit("L7", "DHCP", server_ip, "client_mac",
                   f"OFFER: {pool_first} (lease 3600s)")
        self._emit("L7", "DHCP", "0.0.0.0", "255.255.255.255",
                   f"REQUEST: client accepts offer for {pool_first}")
        self._emit("L7", "DHCP", server_ip, "client_mac",
                   "ACK: lease granted")
        self._emit("L3", "DHCP", server_ip, pool_first,
                   f"client now uses {pool_first}")
        self._emit("L3", "DHCP", pool_first, server_ip,
                   f"renewal due in 1800s (T1) to {server_ip}")
        return self._events
