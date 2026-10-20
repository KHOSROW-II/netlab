"""ARP simulation and live capture."""
import logging

import docker

from ..exceptions import ConfigurationError
from .event import ProtocolEvent
from .simulator import Simulator

logger = logging.getLogger(__name__)


class ARPSimulator(Simulator):
    """Educational ARP resolution triggered by an ICMP ping."""

    def run(self) -> list[ProtocolEvent]:
        src_ip = self._ip(self.src_idx)
        dst_ip = self._ip(self.dst_idx)

        self._emit("L3", "ICMP", src_ip, dst_ip,
                   "ping requested by application")
        self._emit("L3", "ARP", src_ip, dst_ip,
                   f"ARP cache miss for {dst_ip}")
        self._emit("L2", "ARP", "ff:ff:ff:ff:ff:ff", "broadcast",
                   f"WHO-HAS {dst_ip} TELL {src_ip} (broadcast)")
        self._emit("L2", "ARP", "all hosts", "all hosts",
                   "every host receives; only the target answers")
        self._emit("L2", "ARP", "target_mac", src_ip,
                   f"reply: {dst_ip} IS-AT target_mac (unicast)")
        self._emit("L3", "ARP", dst_ip, src_ip,
                   "ARP cache populated")
        self._emit("L3", "ICMP", src_ip, dst_ip,
                   "echo request sent")
        self._emit("L3", "ICMP", dst_ip, src_ip,
                   "echo reply received")
        return self._events


class ARPLive:
    """Live ARP capture: flush cache, ping, inspect neighbour table."""

    def __init__(self, group_name: str, src_idx: int, dst_ip: str) -> None:
        self.group = group_name
        self.src_idx = src_idx
        self.dst_ip = dst_ip
        self._client = docker.from_env()
        self._events: list[ProtocolEvent] = []
        self._step = 0

    def _emit(self, layer, protocol, src, dst, info, at_node="") -> None:
        self._step += 1
        self._events.append(ProtocolEvent(
            step=self._step, layer=layer, protocol=protocol,
            src=src, dst=dst, info=info, at_node=at_node,
        ))

    def run(self) -> list[ProtocolEvent]:
        src_name = f"netlab-{self.group}-host{self.src_idx}"
        try:
            src = self._client.containers.get(src_name)
        except docker.errors.NotFound as exc:
            raise ConfigurationError(
                f"Container {src_name} not found. "
                f"Is the cluster up? (netlab cluster up -f <topology>)"
            ) from exc

        ip_out = src.exec_run(["hostname", "-i"]).output.decode(errors="ignore")
        src_ip = ip_out.strip().split()[0] if ip_out.strip() else "?"

        self._emit("L3", "ICMP", src_ip, self.dst_ip,
                   "ping requested by user", at_node=src_name)

        src.exec_run(["ip", "neigh", "flush", "all"])
        self._emit("L3", "ARP", src_ip, "broadcast",
                   "ARP cache cleared", at_node=src_name)

        result = src.exec_run(["ping", "-c", "1", "-W", "2", self.dst_ip])
        if result.exit_code == 0:
            self._emit("L2", "ARP", src_ip, "broadcast",
                       f"WHO-HAS {self.dst_ip} TELL {src_ip}",
                       at_node=src_name)
            self._emit("L2", "ARP", self.dst_ip, src_ip,
                       "IS-AT reply received", at_node=src_name)
            self._emit("L3", "ICMP", src_ip, self.dst_ip,
                       "echo request sent", at_node=src_name)
            self._emit("L3", "ICMP", self.dst_ip, src_ip,
                       "echo reply received", at_node=src_name)
        else:
            self._emit("L3", "ICMP", src_ip, self.dst_ip,
                       "ping failed", at_node=src_name)

        neigh = src.exec_run(["ip", "neigh", "show", self.dst_ip])
        if neigh.exit_code == 0 and neigh.output.strip():
            line = neigh.output.decode(errors="ignore").strip().splitlines()[0]
            self._emit("L2", "ARP", self.dst_ip, src_ip,
                       f"cache now: {line}", at_node=src_name)
        return self._events
