"""DNS simulation and live query."""
import logging

import docker

from ..exceptions import ConfigurationError
from .event import ProtocolEvent
from .simulator import Simulator

logger = logging.getLogger(__name__)


class DNSSimulator(Simulator):
    """Recursive DNS resolution flow."""

    def __init__(
        self,
        topo,
        group_name: str,
        src_idx: int = 1,
        query: str = "example.com",
        server: str = "8.8.8.8",
        answer_ip: str = "93.184.216.34",
    ) -> None:
        super().__init__(topo, group_name, src_idx=src_idx)
        self.query = query
        self.server = server
        self.answer_ip = answer_ip

    def run(self) -> list[ProtocolEvent]:
        client_ip = self._ip(self.src_idx)

        self._emit("L7", "DNS", client_ip, self.server,
                   f"query A? {self.query} (UDP/53)")
        self._emit("L7", "DNS", self.server, "authoritative_ns",
                   f"recursive lookup for {self.query}")
        self._emit("L7", "DNS", "authoritative_ns", self.server,
                   f"A record {self.answer_ip}")
        self._emit("L7", "DNS", self.server, client_ip,
                   f"response A {self.answer_ip} TTL=300")
        self._emit("L7", "DNS", client_ip, self.answer_ip,
                   "client may now connect")
        return self._events


class DNSLive:
    """Live DNS query executed inside a container."""

    def __init__(self, group_name: str, src_idx: int, query: str,
                 server: str = "8.8.8.8") -> None:
        self.group = group_name
        self.src_idx = src_idx
        self.query = query
        self.server = server
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

        self._emit("L7", "DNS", src_ip, self.server,
                   f"query A? {self.query} (UDP/53)", at_node=src_name)

        result = src.exec_run(["dig", "+short", "+time=3", "+tries=1",
                               self.query, f"@{self.server}"])
        output = result.output.decode(errors="ignore").strip()

        answer = output.splitlines()[0].strip() if output else ""
        if answer and result.exit_code == 0:
            self._emit("L7", "DNS", self.server, src_ip,
                       f"response A {answer}", at_node=src_name)
        else:
            self._emit("L7", "DNS", self.server, src_ip,
                       "no answer (network or DNS unreachable)",
                       at_node=src_name)
        return self._events
