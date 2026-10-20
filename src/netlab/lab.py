"""Lab orchestration: combines network and host managers."""
import logging
from ipaddress import IPv4Network
from typing import List, Optional

import docker

from .ipam import HostIPPlanner, SubnetInfo

from .config import LabConfig
from .exceptions import ConfigurationError
from .host_manager import HostManager
from .models import Host, NetworkConfig
from .network_manager import NetworkManager

logger = logging.getLogger(__name__)


class Lab:
    """Represents a single simulation run."""

    def __init__(self, config: LabConfig) -> None:
        self._config = config
        self._client = docker.from_env()
        self._network_mgr = NetworkManager(self._client)
        self._host_mgr = HostManager(
            self._client, image=config.image, label=config.label
        )
        self._network_config = self._build_network_config()
        self._host_ips = self._plan_host_ips()
        self._hosts: List[Host] = []
        self._network: Optional[docker.models.networks.Network] = None


# replace _build_network_config:
    def _build_network_config(self) -> NetworkConfig:
        try:
            info = SubnetInfo.from_cidr(self._config.subnet)
        except ValueError as exc:
            raise ConfigurationError(f"Invalid subnet: {exc}") from exc
        if info.network.version != 4:
            raise ConfigurationError("Phase 1 supports IPv4 only")
        return NetworkConfig(
            name=self._config.network_name, subnet=info.network
        )

# replace _plan_host_ips:
    def _plan_host_ips(self) -> List[str]:
        planner = HostIPPlanner(
            cidr=self._config.subnet,
            start_offset=self._config.start_ip_offset,
            gateway_offset=1,
        )
        return [a.address for a in planner.plan(self._config.host_count)]

    def deploy(self) -> None:
        """Create the network and all host containers."""
        self.destroy()
        try:
            self._host_mgr.ensure_image()
            self._network = self._network_mgr.create(self._network_config)
            logger.info(
                "Network %s created (%s)",
                self._network_config.name,
                self._network_config.subnet,
            )
            for idx, ip in enumerate(self._host_ips, start=1):
                name = f"netlab-p1-host{idx}"
                host = self._host_mgr.create(
                    name=name, ip=ip, network=self._network
                )
                self._hosts.append(host)
                logger.info("Host %s ready at %s", host.name, host.ip)
        except Exception:
            logger.exception("Deployment failed, cleaning up")
            try:
                self.destroy()
            except Exception:
                logger.exception("Cleanup also failed")
            raise

    def destroy(self) -> None:
        """Remove containers (including orphans) and the network. Idempotent."""
        self._host_mgr.remove_all()
        self._network_mgr.ensure_absent(self._config.network_name)
        self._hosts.clear()
        self._network = None

    def run_connectivity_check(self) -> bool:
        """Ping every host from the first host."""
        if len(self._hosts) < 2:
            logger.warning("Need at least 2 hosts for connectivity check")
            return True
        source = self._hosts[0]
        all_ok = True
        for target in self._hosts[1:]:
            ok = self._host_mgr.ping(source, target.ip)
            logger.info(
                "ping %s -> %s [%s]",
                source.name,
                target.ip,
                "OK" if ok else "FAIL",
            )
            all_ok = all_ok and ok
        return all_ok

    def print_summary(self) -> None:
        print()
        print("=" * 60)
        print("Phase 1 - Summary")
        print("=" * 60)
        print(f"Network     : {self._network_config.name}")
        print(f"Subnet      : {self._network_config.subnet}")
        print(f"Gateway     : {self._network_config.gateway}")
        print(f"Hosts       : {len(self._hosts)}")
        for host in self._hosts:
            print(f"  - {host.name:<20} {host.ip}")
        print()
        print("Interactive shell:")
        for host in self._hosts:
            print(f"  docker exec -it {host.name} bash")
        print()
        print(
            f"Cleanup: netlab --cleanup --network-name "
            f"{self._network_config.name}"
        )
        print("=" * 60)