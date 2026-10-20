"""Auto-remediation for common NetLab environment problems."""
import logging
from dataclasses import dataclass, field

import docker
from docker.errors import APIError

from .firewall import SYSCTL_KEY, SYSCTL_KEY6
from .platform import PlatformAdapter, detect_platform
from .topology import PLACEHOLDER_KINDS, LabTopology

logger = logging.getLogger(__name__)


@dataclass
class FixAction:
    label: str
    success: bool
    detail: str


@dataclass
class FixReport:
    actions: list[FixAction] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(a.success for a in self.actions)

    def print(self) -> None:
        if not self.actions:
            print("No fixes were needed.")
            return
        for a in self.actions:
            mark = "[ OK ]" if a.success else "[FAIL]"
            print(f"{mark} {a.label}: {a.detail}")


class Fixer:
    def __init__(
        self,
        topology: LabTopology | None = None,
        client: docker.DockerClient | None = None,
        adapter: PlatformAdapter | None = None,
    ) -> None:
        self.topology = topology
        self.adapter = adapter or detect_platform()
        self._client = client

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def run(self) -> FixReport:
        report = FixReport()
        report.actions.append(self._fix_br_netfilter())
        if self.topology is not None:
            report.actions.extend(self._fix_cluster_resources())
        return report

    def _fix_br_netfilter(self) -> FixAction:
        value = self.adapter.read_sysctl(SYSCTL_KEY)
        if value != "1":
            return FixAction(
                "br_netfilter", True, f"already OK (value={value!r})",
            )
        admin = self.adapter.admin_status()
        if not (admin.is_admin or admin.can_elevate):
            cmds = self.adapter.persist_commands(SYSCTL_KEY, "0")
            cmds += self.adapter.persist_commands(SYSCTL_KEY6, "0")
            hint = " ; ".join(cmds) if cmds else admin.hint
            return FixAction(
                "br_netfilter", False,
                f"enabled, not privileged. Run: {hint}",
            )
        ok1 = self.adapter.apply_sysctl(SYSCTL_KEY, "0")
        ok2 = self.adapter.apply_sysctl(SYSCTL_KEY6, "0")
        return FixAction(
            "br_netfilter", ok1 and ok2,
            "disabled" if ok1 and ok2 else "failed to disable",
        )

    def _expected_container_names(self) -> set[str]:
        if not self.topology:
            return set()
        names: set[str] = set()
        for g in self.topology.groups:
            for i in range(1, g.host_count + 1):
                names.add(f"netlab-{g.name}-host{i}")
            ph = PLACEHOLDER_KINDS.get(g.topology)
            if ph is not None:
                names.add(f"netlab-{g.name}-{ph}")
        for r in self.topology.routers:
            names.add(f"netlab-{r.name}")
        for s in self.topology.services:
            names.add(f"netlab-{s.group}-dnsmasq")
        return names

    def _expected_network_names(self) -> set[str]:
        if not self.topology:
            return set()
        names: set[str] = set()
        for g in self.topology.groups:
            if g.topology.value == "ring":
                for i in range(g.host_count):
                    names.add(f"netlab-{g.name}-ring{i}")
            else:
                names.add(f"netlab-{g.name}")
        return names

    def _fix_cluster_resources(self) -> list[FixAction]:
        actions: list[FixAction] = []
        name = self.topology.name
        expected = self._expected_container_names()
        expected_nets = self._expected_network_names()
        try:
            containers = self.client.containers.list(
                all=True, filters={"label": f"netlab={name}"}
            )
        except APIError as exc:
            return [FixAction("list containers", False, str(exc))]
        for c in containers:
            if c.name not in expected:
                try:
                    c.remove(force=True)
                    actions.append(FixAction(
                        f"orphan {c.name}", True, "removed",
                    ))
                except APIError as exc:
                    actions.append(FixAction(
                        f"orphan {c.name}", False, str(exc),
                    ))
        for c in containers:
            if c.name in expected and c.status != "running":
                try:
                    c.start()
                    actions.append(FixAction(
                        f"restart {c.name}", True, "started",
                    ))
                except APIError as exc:
                    actions.append(FixAction(
                        f"restart {c.name}", False, str(exc),
                    ))
        try:
            networks = self.client.networks.list(
                filters={"label": f"netlab={name}"}
            )
        except APIError as exc:
            return actions + [FixAction("list networks", False, str(exc))]
        for net in networks:
            if net.name not in expected_nets:
                try:
                    net.remove()
                    actions.append(FixAction(
                        f"orphan network {net.name}", True, "removed",
                    ))
                except APIError as exc:
                    actions.append(FixAction(
                        f"orphan network {net.name}", False, str(exc),
                    ))
        if not actions:
            actions.append(FixAction(
                "cluster resources", True,
                "no orphans, all containers running",
            ))
        return actions