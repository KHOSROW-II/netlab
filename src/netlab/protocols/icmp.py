"""ICMP simulation and live ping."""
import logging

import docker

from ..exceptions import ConfigurationError
from .event import ProtocolEvent
from .simulator import Simulator

logger = logging.getLogger(__name__)


class ICMPSimulator(Simulator):
    """ICMP echo request/reply flow within one subnet."""

    def run(self) -> list[ProtocolEvent]:
        src_ip = self._ip(self.src_idx)
        dst_ip = self._ip(self.dst_idx)

        self._emit("L3", "ICMP", src_ip, dst_ip,
                   "echo request type=8 code=0 (ping)")
        self._emit("L3", "ICMP", dst_ip, src_ip,
                   "echo reply type=0 code=0")
        self._emit("L3", "ICMP", src_ip, dst_ip,
                   "RTT measured, packet counted")
        return self._events


class ICMPLive:
    """Live ICMP ping with statistics parsed from real output."""

    def __init__(self, group_name: str, src_idx: int, dst_ip: str,
                 count: int = 4) -> None:
        self.group = group_name
        self.src_idx = src_idx
        self.dst_ip = dst_ip
        self.count = count
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
                   f"ping x{self.count} started", at_node=src_name)

        result = src.exec_run(
            ["ping", "-c", str(self.count), "-W", "2", self.dst_ip]
        )
        output = result.output.decode(errors="ignore")

        for line in output.splitlines():
            if "packets transmitted" in line:
                self._emit("L3", "ICMP", src_ip, self.dst_ip,
                           f"stats: {line.strip()}", at_node=src_name)
                break
        for line in output.splitlines():
            if "min/avg/max" in line:
                self._emit("L3", "ICMP", src_ip, self.dst_ip,
                           f"rtt: {line.strip()}", at_node=src_name)
                break

        verdict = "success" if result.exit_code == 0 else "failure"
        self._emit("L3", "ICMP", src_ip, self.dst_ip,
                   f"exit code {result.exit_code} ({verdict})",
                   at_node=src_name)
        return self._events
