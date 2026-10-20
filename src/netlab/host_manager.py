"""Docker container lifecycle management for simulated hosts."""
import logging

import docker
from docker.errors import APIError, ImageNotFound, NotFound
from docker.errors import ContainerError as DockerContainerError

from .exceptions import ContainerError
from .models import Host

logger = logging.getLogger(__name__)


class HostManager:
    def __init__(self, client: docker.DockerClient, image: str, label: str) -> None:
        self._client = client
        self._image = image
        self._label = label

    def ensure_image(self) -> None:
        try:
            self._client.images.get(self._image)
            logger.debug("Image %s already present", self._image)
        except ImageNotFound:
            logger.info("Pulling image %s", self._image)
            self._client.images.pull(self._image)

    def _detach_default_bridge(
        self,
        container: docker.models.containers.Container,
        keep_network: str,
    ) -> None:
        """Remove the container from Docker's default bridge once attached
        to the lab network, so it never appears with a 172.17.x.x IP."""
        try:
            default = self._client.networks.get("bridge")
        except (NotFound, APIError):
            return
        if default.name == keep_network:
            return
        try:
            default.disconnect(container, force=True)
            logger.debug(
                "Detached %s from default bridge", container.name,
            )
        except APIError as exc:
            logger.debug(
                "Could not detach %s from default bridge: %s",
                container.name, exc,
            )

    def create(
        self,
        name: str,
        ip: str,
        network: docker.models.networks.Network,
        extra_labels: dict[str, str] | None = None,
        dns_servers: tuple[str, ...] = (),
        search_domains: tuple[str, ...] = (),
        sysctls: dict[str, str] | None = None,
        privileged: bool = False,
    ) -> Host:
        labels = {"netlab": self._label, **(extra_labels or {})}
        try:
            container = self._client.containers.run(
                image=self._image,
                command=["tail", "-f", "/dev/null"],
                name=name,
                detach=True,
                labels=labels,
                dns=list(dns_servers) or None,
                dns_search=list(search_domains) or None,
                cap_add=["NET_ADMIN"],
                sysctls=sysctls or None,
                privileged=privileged,
            )
        except DockerContainerError as exc:
            raise ContainerError(f"Failed to start {name}: {exc}") from exc
        try:
            network.connect(container, ipv4_address=ip)
        except APIError as exc:
            container.remove(force=True)
            raise ContainerError(
                f"Failed to attach {name} to {network.name} with IP {ip}: {exc}"
            ) from exc
        self._detach_default_bridge(container, network.name)
        container.reload()
        actual = container.attrs.get("NetworkSettings", {}).get("Networks", {})
        actual_ip = actual.get(network.name, {}).get("IPAddress", "")
        if actual_ip != ip:
            container.remove(force=True)
            raise ContainerError(
                f"{name} expected IP {ip} but got {actual_ip or 'none'}"
            )
        return Host(
            name=name, ip=actual_ip, container_id=container.id,
            image=self._image, networks={network.name: actual_ip},
        )

    def create_multi(
        self,
        name: str,
        network_ips: dict[str, str],
        extra_labels: dict[str, str] | None = None,
        dns_servers: tuple[str, ...] = (),
        search_domains: tuple[str, ...] = (),
        sysctls: dict[str, str] | None = None,
        privileged: bool = False,
    ) -> Host:
        if not network_ips:
            raise ContainerError(f"{name} needs at least one network")
        labels = {"netlab": self._label, **(extra_labels or {})}
        try:
            container = self._client.containers.run(
                image=self._image,
                command=["tail", "-f", "/dev/null"],
                name=name,
                detach=True,
                labels=labels,
                dns=list(dns_servers) or None,
                dns_search=list(search_domains) or None,
                cap_add=["NET_ADMIN"],
                sysctls=sysctls or None,
                privileged=privileged,
            )
        except DockerContainerError as exc:
            raise ContainerError(f"Failed to start {name}: {exc}") from exc
        connected = []
        try:
            for net_name, ip in network_ips.items():
                net = self._client.networks.get(net_name)
                net.connect(container, ipv4_address=ip)
                connected.append(net)
        except APIError as exc:
            for net in connected:
                try:
                    net.disconnect(container, force=True)
                except APIError:
                    pass
            container.remove(force=True)
            raise ContainerError(f"Failed to attach {name}: {exc}") from exc
        # Keep the first named network; remove the default bridge
        first_net = next(iter(network_ips.keys()))
        self._detach_default_bridge(container, first_net)
        container.reload()
        actual = container.attrs.get("NetworkSettings", {}).get("Networks", {})
        actual_map = {n: d.get("IPAddress", "") for n, d in actual.items()}
        for n, expected in network_ips.items():
            if actual_map.get(n) != expected:
                container.remove(force=True)
                raise ContainerError(
                    f"{name}: expected {expected} on {n}, "
                    f"got {actual_map.get(n, 'none')}"
                )
        return Host(
            name=name, ip=next(iter(network_ips.values())),
            container_id=container.id, image=self._image,
            networks=actual_map,
        )

    def ping(self, source: Host, target_ip: str, count: int = 1,
             timeout: int = 2) -> bool:
        container = self._client.containers.get(source.container_id)
        result = container.exec_run(
            ["ping", "-c", str(count), "-W", str(timeout), target_ip]
        )
        return result.exit_code == 0

    def exec_cmd(self, name: str, cmd: list[str]) -> tuple[int, str]:
        container = self._client.containers.get(name)
        result = container.exec_run(cmd)
        return result.exit_code, result.output.decode(errors="ignore")

    def set_dns(self, name: str, servers: list[str],
                search_domains: list[str] | None = None) -> None:
        container = self._client.containers.get(name)
        content = ""
        if search_domains:
            content += "search " + " ".join(search_domains) + "\n"
        for server in servers:
            content += f"nameserver {server}\n"
        script = (
            "cat > /etc/resolv.conf << 'NETLAB_RESOLV_EOF'\n"
            f"{content}"
            "NETLAB_RESOLV_EOF"
        )
        result = container.exec_run(["sh", "-c", script])
        if result.exit_code != 0:
            raise ContainerError(
                f"Failed to set DNS on {name}: "
                f"{result.output.decode(errors='ignore').strip()}"
            )

    def set_ip(self, name: str, new_ip: str, network_name: str) -> None:
        container = self._client.containers.get(name)
        network = self._client.networks.get(network_name)
        try:
            network.disconnect(container, force=True)
        except APIError as exc:
            logger.debug("disconnect failed: %s", exc)
        try:
            network.connect(container, ipv4_address=new_ip)
        except APIError as exc:
            raise ContainerError(
                f"Failed to set IP {new_ip} on {name}@{network_name}: {exc}"
            ) from exc

    def set_default_route(self, name: str, gateway_ip: str) -> None:
        container = self._client.containers.get(name)
        result = container.exec_run(
            ["ip", "route", "replace", "default", "via", gateway_ip]
        )
        if result.exit_code != 0:
            raise ContainerError(
                f"Failed to set default route on {name} via {gateway_ip}: "
                f"{result.output.decode(errors='ignore').strip()}"
            )

    def enable_forwarding(self, name: str) -> None:
        container = self._client.containers.get(name)
        result = container.exec_run(
            ["sh", "-c",
             "sysctl -w net.ipv4.ip_forward=1 2>/dev/null "
             "|| echo 1 > /proc/sys/net/ipv4/ip_forward"]
        )
        if result.exit_code != 0:
            raise ContainerError(
                f"Failed to enable forwarding on {name}: "
                f"{result.output.decode(errors='ignore').strip()}"
            )

    def stop(self, name: str) -> None:
        self._client.containers.get(name).stop()

    def start(self, name: str) -> None:
        self._client.containers.get(name).start()

    def container_status(self, name: str) -> str:
        try:
            return self._client.containers.get(name).status
        except NotFound:
            return "missing"

    def remove_all(self) -> None:
        try:
            containers = self._client.containers.list(
                all=True, filters={"label": f"netlab={self._label}"}
            )
        except APIError as exc:
            raise ContainerError(f"Failed to list containers: {exc}") from exc
        for c in containers:
            try:
                c.remove(force=True)
            except APIError as exc:
                logger.warning("Could not remove %s: %s", c.name, exc)