"""One logical group of hosts backed by one or more Docker networks."""
import logging
from ipaddress import IPv4Network

import docker

from .exceptions import ConfigurationError
from .host_manager import HostManager
from .ipam import HostIPPlanner, split_by_count
from .models import Host, NetworkConfig
from .network_manager import NetworkManager
from .topology import PLACEHOLDER_KINDS, GroupSpec, TopologyType

logger = logging.getLogger(__name__)

ALPINE = "alpine:3.19"


class Group:
    def __init__(
        self, spec: GroupSpec, client: docker.DockerClient,
        image: str, cluster_name: str,
    ) -> None:
        self.spec = spec
        self._client = client
        self._image = image
        self._cluster_name = cluster_name
        self._network_mgr = NetworkManager(client)
        self._host_mgr = HostManager(client, image=image, label=cluster_name)
        self._networks: dict[str, docker.models.networks.Network] = {}
        self._hosts: list[Host] = []

    @property
    def host_names(self) -> list[str]:
        return [h.name for h in self._hosts]

    def _labels(self) -> dict[str, str]:
        return {
            "netlab": self._cluster_name,
            "netlab.group": self.spec.name,
        }

    def deploy(self) -> None:
        self.destroy()
        self._host_mgr.ensure_image()
        if self.spec.topology == TopologyType.RING:
            self._deploy_ring()
        else:
            self._deploy_shared()
        logger.info(
            "Group %s deployed (%s, %d hosts)",
            self.spec.name, self.spec.topology.value, len(self._hosts),
        )

    def _deploy_shared(self) -> None:
        planner = HostIPPlanner(
            cidr=self.spec.subnet,
            start_offset=self.spec.start_offset,
            gateway_offset=self.spec.gateway_offset,
        )
        net_name = f"netlab-{self.spec.name}"
        net_config = NetworkConfig(name=net_name, subnet=planner.info.network)
        network = self._network_mgr.create(net_config, labels=self._labels())
        self._networks[net_name] = network

        # Placeholder device container (switch / hub / ap) if applicable.
        placeholder = PLACEHOLDER_KINDS.get(self.spec.topology)
        if placeholder is not None:
            self._deploy_placeholder_device(network, planner, placeholder)

        for i, addr in enumerate(planner.plan(self.spec.host_count), start=1):
            host_name = f"netlab-{self.spec.name}-host{i}"
            host = self._host_mgr.create(
                name=host_name, ip=addr.address, network=network,
                extra_labels={"netlab.group": self.spec.name},
                dns_servers=self.spec.dns_servers,
                search_domains=self.spec.search_domains,
            )
            self._hosts.append(host)

    def _deploy_placeholder_device(self, network, planner, placeholder_kind):
        """Create an alpine container that represents a switch/hub/ap on the
        group network. It has a management IP and shows up in `docker ps`,
        the graph, and the terminal dropdown."""
        mgmt_offset = 2
        mgmt_ip = str(planner.info.network.network_address + mgmt_offset)
        # If the gateway is already .2, use .3
        if mgmt_ip == planner.gateway:
            mgmt_ip = str(planner.info.network.network_address + 3)
        name = f"netlab-{self.spec.name}-{placeholder_kind}"
        try:
            container = self._client.containers.run(
                image=ALPINE,
                command=["tail", "-f", "/dev/null"],
                name=name,
                detach=True,
                labels={
                    "netlab": self._cluster_name,
                    "netlab.role": placeholder_kind,
                    "netlab.group": self.spec.name,
                },
            )
        except docker.errors.ContainerError as exc:
            raise ConfigurationError(
                f"Failed to start {placeholder_kind} on {self.spec.name}: {exc}"
            ) from exc
        try:
            network.connect(container, ipv4_address=mgmt_ip)
        except docker.errors.APIError as exc:
            container.remove(force=True)
            raise ConfigurationError(
                f"Failed to attach {placeholder_kind} {name} to "
                f"{network.name} with IP {mgmt_ip}: {exc}"
            ) from exc
        # Detach from default bridge (same policy as hosts)
        try:
            default = self._client.networks.get("bridge")
            if default.name != network.name:
                default.disconnect(container, force=True)
        except (docker.errors.NotFound, docker.errors.APIError):
            pass
        logger.info(
            "%s %s ready at %s", placeholder_kind, name, mgmt_ip,
        )

    def _deploy_ring(self) -> None:
        n = self.spec.host_count
        pair_subnets = split_by_count(self.spec.subnet, n)[:n]
        if len(pair_subnets) < n:
            raise ConfigurationError(
                f"Cannot split {self.spec.subnet} into {n} ring segments"
            )
        ring_net_names: list[str] = []
        for i, subnet_info in enumerate(pair_subnets):
            net_name = f"netlab-{self.spec.name}-ring{i}"
            net_config = NetworkConfig(name=net_name, subnet=subnet_info.network)
            network = self._network_mgr.create(net_config, labels=self._labels())
            self._networks[net_name] = network
            ring_net_names.append(net_name)
        for i in range(n):
            host_name = f"netlab-{self.spec.name}-host{i + 1}"
            left_idx = (i - 1) % n
            right_idx = i
            left_base = pair_subnets[left_idx].network.network_address
            right_base = pair_subnets[right_idx].network.network_address
            network_ips = {
                ring_net_names[left_idx]: str(left_base + 11),
                ring_net_names[right_idx]: str(right_base + 10),
            }
            host = self._host_mgr.create_multi(
                name=host_name, network_ips=network_ips,
                extra_labels={"netlab.group": self.spec.name},
                dns_servers=self.spec.dns_servers,
                search_domains=self.spec.search_domains,
                sysctls={"net.ipv4.ip_forward": "1"},
                privileged=True,
            )
            self._hosts.append(host)

    def destroy(self) -> None:
        try:
            containers = self._client.containers.list(
                all=True,
                filters={"label": [
                    f"netlab={self._cluster_name}",
                    f"netlab.group={self.spec.name}",
                ]},
            )
            for c in containers:
                try:
                    c.remove(force=True)
                except Exception as exc:
                    logger.warning("Could not remove %s: %s", c.name, exc)
        except Exception as exc:
            logger.warning("Listing group containers failed: %s", exc)
        for net_name in list(self._networks.keys()):
            self._network_mgr.ensure_absent(net_name)
        self._networks.clear()
        self._hosts.clear()

    def exec(self, host_name: str, cmd: list[str]) -> tuple[int, str]:
        return self._host_mgr.exec_cmd(host_name, cmd)

    def set_dns(self, host_name: str, servers: list[str],
                search_domains: list[str] | None = None) -> None:
        self._host_mgr.set_dns(host_name, servers, search_domains)

    def set_ip(self, host_name: str, new_ip: str) -> None:
        if self.spec.topology == TopologyType.RING:
            raise ConfigurationError(
                "set-ip is not supported on ring topology groups"
            )
        self._host_mgr.set_ip(host_name, new_ip, f"netlab-{self.spec.name}")