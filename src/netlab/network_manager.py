"""Docker network lifecycle management."""
import logging
from ipaddress import IPv4Network

import docker
from docker.errors import APIError, NotFound
from docker.types import IPAMConfig, IPAMPool

from .exceptions import NetworkError
from .models import NetworkConfig

logger = logging.getLogger(__name__)


class NetworkManager:
    def __init__(self, client: docker.DockerClient) -> None:
        self._client = client

    # ------------------------------------------------------------------ checks

    def _check_no_overlap(
        self,
        subnet_cidr,
        new_name: str,
        auto_cleanup: bool = True,
    ) -> None:
        """Raise NetworkError if subnet_cidr overlaps an existing network.

        If the conflicting network is a NetLab orphan (name starts with
        'netlab-'), remove it first and continue — so a leftover from a
        crashed run does not block the next deploy.
        """
        target = IPv4Network(str(subnet_cidr), strict=False)
        try:
            all_networks = self._client.networks.list()
        except APIError:
            return
        for net in all_networks:
            if net.name == new_name:
                continue
            for cfg in net.attrs.get("IPAM", {}).get("Config", []) or []:
                subnet = cfg.get("Subnet")
                if not subnet:
                    continue
                try:
                    existing = IPv4Network(subnet, strict=False)
                except ValueError:
                    continue
                if existing.version != target.version:
                    continue
                if not existing.overlaps(target):
                    continue
                # Conflict found
                if auto_cleanup and net.name.startswith("netlab-"):
                    logger.warning(
                        "Auto-removing orphan network %s (%s) that "
                        "overlaps %s", net.name, subnet, subnet_cidr,
                    )
                    try:
                        net.remove()
                        break  # moved on; try next network
                    except APIError as exc:
                        raise NetworkError(
                            f"Cannot create network '{new_name}' with "
                            f"{subnet_cidr}: overlaps with '{net.name}' "
                            f"({subnet}). Auto-cleanup failed: {exc}. "
                            f"Remove manually: docker network rm {net.name}"
                        ) from exc
                raise NetworkError(
                    f"Cannot create network '{new_name}' with {subnet_cidr}: "
                    f"overlaps with existing Docker network '{net.name}' "
                    f"({subnet}). Remove it first: docker network rm {net.name}"
                )

    # ------------------------------------------------------------------ create

    def create(
        self,
        config: NetworkConfig,
        labels: dict[str, str] | None = None,
    ) -> docker.models.networks.Network:
        self._check_no_overlap(config.subnet, config.name)
        pool = IPAMPool(subnet=str(config.subnet), gateway=config.gateway)
        ipam = IPAMConfig(pool_configs=[pool])
        try:
            network = self._client.networks.create(
                config.name,
                driver="bridge",
                ipam=ipam,
                check_duplicate=True,
                labels=labels or {},
            )
        except APIError as exc:
            raise NetworkError(
                f"Failed to create network {config.name}: {exc}"
            ) from exc
        logger.debug("Network %s created", config.name)
        return network

    # ------------------------------------------------------------------ remove

    def ensure_absent(self, name: str) -> None:
        try:
            network = self._client.networks.get(name)
        except NotFound:
            logger.debug("Network %s not present", name)
            return
        try:
            network.remove()
            logger.debug("Network %s removed", name)
        except APIError as exc:
            raise NetworkError(
                f"Failed to remove network {name}: {exc}"
            ) from exc

    def remove_all_for_cluster(self, cluster_name: str) -> None:
        # By label
        try:
            networks = self._client.networks.list(
                filters={"label": f"netlab={cluster_name}"}
            )
            for network in networks:
                try:
                    network.remove()
                    logger.debug("Network %s removed", network.name)
                except APIError as exc:
                    logger.warning(
                        "Could not remove network %s: %s",
                        network.name, exc,
                    )
        except APIError as exc:
            raise NetworkError(
                f"Failed to list networks: {exc}"
            ) from exc

        # By name prefix (catches orphans without labels)
        prefix = f"netlab-{cluster_name}"
        try:
            for network in self._client.networks.list():
                if network.name.startswith(prefix):
                    try:
                        network.remove()
                        logger.debug(
                            "Orphan network %s removed", network.name,
                        )
                    except APIError as exc:
                        logger.warning(
                            "Could not remove %s: %s", network.name, exc,
                        )
        except APIError as exc:
            logger.warning(
                "Orphan network cleanup failed: %s", exc,
            )