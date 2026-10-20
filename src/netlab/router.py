"""Multi-group router container."""
import logging

import docker

from .exceptions import ConfigurationError
from .host_manager import HostManager
from .topology import LabTopology, RouterSpec

logger = logging.getLogger(__name__)


class Router:
    def __init__(
        self,
        spec: RouterSpec,
        client: docker.DockerClient,
        topology: LabTopology,
        cluster_name: str,
    ) -> None:
        self.spec = spec
        self.topology = topology
        self._client = client
        self._cluster_name = cluster_name
        self._host_mgr = HostManager(
            client, image=spec.image, label=cluster_name
        )

    @property
    def container_name(self) -> str:
        return f"netlab-{self.spec.name}"

    def _ip_for_group(self, group_name: str) -> str:
        group = self.topology.group(group_name)
        from ipaddress import IPv4Network
        net = IPv4Network(group.subnet, strict=False)
        return str(net.network_address + self.spec.ip_suffix)

    def deploy(self) -> None:
        self._host_mgr.ensure_image()
        network_ips = {
            f"netlab-{g}": self._ip_for_group(g)
            for g in self.spec.connects
        }
        try:
            self._host_mgr.create_multi(
                name=self.container_name,
                network_ips=network_ips,
                extra_labels={"netlab.role": "router"},
                sysctls={"net.ipv4.ip_forward": "1"},
                privileged=True,
            )
        except Exception as exc:
            raise ConfigurationError(
                f"Failed to deploy router {self.spec.name}: {exc}"
            ) from exc

        # Verify forwarding is actually on; if not, raise loudly.
        code, out = self._host_mgr.exec_cmd(
            self.container_name, ["sysctl", "-n", "net.ipv4.ip_forward"]
        )
        value = out.strip()
        if value != "1":
            raise ConfigurationError(
                f"Router {self.spec.name}: ip_forward={value!r} "
                f"(expected '1')"
            )

        first_group = self.spec.connects[0]
        first_gw = (
            f"{'.'.join(self._ip_for_group(first_group).split('.')[:3])}.1"
        )
        try:
            self._host_mgr.set_default_route(self.container_name, first_gw)
        except Exception as exc:
            logger.warning(
                "Could not set router default route via %s: %s",
                first_gw, exc,
            )

        logger.info(
            "Router %s up on %d networks (forwarding=on)",
            self.spec.name, len(network_ips),
        )

    def host_default_gateway(self, group_name: str) -> str:
        return self._ip_for_group(group_name)