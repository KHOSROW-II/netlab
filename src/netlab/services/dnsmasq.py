"""dnsmasq container providing DNS and optional DHCP for one group."""
import logging
import time
from ipaddress import IPv4Network

import docker

from ..exceptions import ConfigurationError
from ..host_manager import HostManager
from ..topology import LabTopology, ServiceSpec

logger = logging.getLogger(__name__)

ALPINE = "alpine:3.19"
READINESS_TIMEOUT = 30
READINESS_INTERVAL = 2


class DnsmasqService:
    def __init__(
        self,
        spec: ServiceSpec,
        client: docker.DockerClient,
        topology: LabTopology,
        cluster_name: str,
    ) -> None:
        self.spec = spec
        self.topology = topology
        self._client = client
        self._cluster_name = cluster_name
        self._host_mgr = HostManager(
            client, image=ALPINE, label=cluster_name
        )

    @property
    def container_name(self) -> str:
        return f"netlab-{self.spec.group}-dnsmasq"

    def _service_ip(self) -> str:
        group = self.topology.group(self.spec.group)
        net = IPv4Network(group.subnet, strict=False)
        return str(net.network_address + self.spec.ip_suffix)

    def _build_config(self) -> str:
        group = self.topology.group(self.spec.group)
        net = IPv4Network(group.subnet, strict=False)
        lo, hi = self.spec.dhcp_range
        range_start = str(net.network_address + lo)
        range_end = str(net.network_address + hi)
        lines = [
            "bind-dynamic",
            "no-resolv",
            "no-poll",
            "user=root",              # never drop privileges; we need port 53/67
            "server=" + self.spec.upstream,
            "server=1.1.1.1",
            "domain-needed",
            "bogus-priv",
            "log-queries",
            "log-dhcp",
            "log-facility=-",         # log to stdout so `docker logs` shows it
            f"dhcp-range={range_start},{range_end},12h",
            f"dhcp-option=option:dns-server,{self._service_ip()}",
        ]
        return "\n".join(lines) + "\n"

    def deploy(self) -> None:
        network_name = f"netlab-{self.spec.group}"
        try:
            network = self._client.networks.get(network_name)
        except docker.errors.NotFound as exc:
            raise ConfigurationError(
                f"Group network {network_name} not found. Is the cluster up?"
            ) from exc

        self._host_mgr.ensure_image()

        config = self._build_config()
        # Do not silence apk output; if it fails, docker logs will show why.
        command = (
            "set -e\n"
            "apk add --no-cache dnsmasq\n"
            "cat > /etc/dnsmasq.conf << 'DNSMASQ_EOF'\n"
            f"{config}"
            "DNSMASQ_EOF\n"
            "exec dnsmasq -k --log-facility=-\n"
        )

        try:
            container = self._client.containers.run(
                image=ALPINE,
                command=["sh", "-c", command],
                name=self.container_name,
                detach=True,
                cap_add=["NET_ADMIN", "NET_RAW"],
                labels={
                    "netlab": self._cluster_name,
                    "netlab.role": "service",
                    "netlab.service": "dnsmasq",
                    "netlab.group": self.spec.group,
                },
            )
        except docker.errors.ContainerError as exc:
            raise ConfigurationError(
                f"Failed to start dnsmasq on {self.spec.group}: {exc}"
            ) from exc
        except docker.errors.APIError as exc:
            raise ConfigurationError(
                f"Failed to create dnsmasq on {self.spec.group}: {exc}"
            ) from exc

        try:
            network.connect(container, ipv4_address=self._service_ip())
        except docker.errors.APIError as exc:
            container.remove(force=True)
            raise ConfigurationError(
                f"Failed to attach dnsmasq to {network_name} "
                f"with IP {self._service_ip()}: {exc}"
            ) from exc

        # Readiness probe: dnsmasq must answer a real query before we
        # declare success. Otherwise `apk add` failures or bind errors
        # would only surface much later as "connection refused".
        self._wait_ready(container)
        self._configure_hosts_dns()
        logger.info(
            "dnsmasq ready on %s at %s",
            self.spec.group, self._service_ip(),
        )
        return container

    def _wait_ready(self, container) -> None:
        """Poll until dnsmasq answers a DNS query, or fail with logs."""
        test_host = f"netlab-{self.spec.group}-host1"
        deadline = time.time() + READINESS_TIMEOUT
        last_err = ""
        while time.time() < deadline:
            # Fail fast if the container has already exited.
            container.reload()
            if container.status == "exited":
                logs = container.logs().decode(errors="ignore").strip()
                container.remove(force=True)
                raise ConfigurationError(
                    f"dnsmasq on {self.spec.group} exited during startup. "
                    f"Logs:\n{logs or '(no logs)'}"
                )
            try:
                client = self._client.containers.get(test_host)
                r = client.exec_run(
                    ["nslookup", "example.com", self._service_ip()]
                )
                if r.exit_code == 0:
                    return
                last_err = r.output.decode(errors="ignore").strip()
            except docker.errors.NotFound:
                last_err = f"client {test_host} not found yet"
            except docker.errors.APIError as exc:
                last_err = str(exc)
            time.sleep(READINESS_INTERVAL)

        logs = container.logs().decode(errors="ignore").strip()
        container.remove(force=True)
        raise ConfigurationError(
            f"dnsmasq on {self.spec.group} did not answer within "
            f"{READINESS_TIMEOUT}s.\n"
            f"Last client error: {last_err}\n"
            f"dnsmasq logs:\n{logs or '(none)'}"
        )

    def _configure_hosts_dns(self) -> None:
        group = self.topology.group(self.spec.group)
        for idx in range(1, group.host_count + 1):
            host_name = f"netlab-{self.spec.group}-host{idx}"
            try:
                self._host_mgr.set_dns(host_name, [self._service_ip()], None)
            except Exception as exc:
                logger.warning(
                    "Could not update DNS on %s: %s", host_name, exc
                )

    def destroy(self) -> None:
        try:
            c = self._client.containers.get(self.container_name)
            c.remove(force=True)
        except docker.errors.NotFound:
            return