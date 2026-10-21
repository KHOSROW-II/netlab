"""Multi-group router container."""
import logging

import docker

from .exceptions import ConfigurationError
from .host_manager import HostManager
from .topology import LabTopology, RouterSpec, TopologyType

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
        self._host_mgr = HostManager(client, image=spec.image, label=cluster_name)
        self._actual_ips = {}

    @property
    def container_name(self) -> str:
        return f"netlab-{self.spec.name}"

    def _ip_for_group(self, group_name: str, suffix: int = None) -> str:
        group = self.topology.group(group_name)
        from ipaddress import IPv4Network
        net = IPv4Network(group.subnet, strict=False)
        suf = suffix if suffix is not None else self.spec.ip_suffix
        return str(net.network_address + suf)

    def deploy(self, suffix_map: dict[str, int] = None) -> None:
        if suffix_map is None:
            suffix_map = {}
            
        self._host_mgr.ensure_image()
        network_ips = {}
        
        for g in self.spec.connects:
            # --- SECURITY CHECK ---
            g_spec = self.topology.group(g)
            if g_spec.topology == TopologyType.RING:
                raise ConfigurationError(
                    f"Cannot connect Router '{self.spec.name}' to Ring group '{g}'. "
                    "A Router requires a single broadcast domain. Change group to 'switch'."
                )
            # ----------------------
            
            suffix = suffix_map.get(g, self.spec.ip_suffix)
            ip = self._ip_for_group(g, suffix)
            self._actual_ips[g] = ip
            network_ips[f"netlab-{g}"] = ip

        try:
            self._host_mgr.create_multi(
                name=self.container_name,
                network_ips=network_ips,
                extra_labels={"netlab.role": "router"},
                sysctls={"net.ipv4.ip_forward": "1"},
                privileged=True,
            )
        except Exception as exc:
            raise ConfigurationError(f"Failed to deploy router {self.spec.name}: {exc}") from exc

        code, out = self._host_mgr.exec_cmd(self.container_name, ["sysctl", "-n", "net.ipv4.ip_forward"])
        value = out.strip()
        if value != "1":
            raise ConfigurationError(f"Router {self.spec.name}: ip_forward={value!r} (expected '1')")

        first_group = self.spec.connects[0]
        first_gw = f"{'.'.join(network_ips[f'netlab-{first_group}'].split('.')[:3])}.1"
        try:
            self._host_mgr.set_default_route(self.container_name, first_gw)
        except Exception as exc:
            logger.warning("Could not set router default route via %s: %s", first_gw, exc)

        logger.info("Router %s up on %d networks (forwarding=on)", self.spec.name, len(network_ips))

    def host_default_gateway(self, group_name: str) -> str:
        return self._actual_ips.get(group_name, self._ip_for_group(group_name))