"""Watch a cluster and restart dead containers."""
import logging
import time

import docker
from docker.errors import APIError, NotFound

from .topology import LabTopology

logger = logging.getLogger(__name__)


class ClusterWatcher:
    """Poll a running cluster; restart dead containers up to a limit."""

    def __init__(
        self,
        topology: LabTopology,
        interval: int = 5,
        max_restarts: int = 3,
        client: docker.DockerClient | None = None,
    ) -> None:
        self.topology = topology
        self.interval = interval
        self.max_restarts = max_restarts
        self._client = client or docker.from_env()
        self._restarts: dict[str, int] = {}

    def _expected(self) -> list[str]:
        names = []
        for g in self.topology.groups:
            for i in range(1, g.host_count + 1):
                names.append(f"netlab-{g.name}-host{i}")
        for r in self.topology.routers:
            names.append(f"netlab-{r.name}")
        for s in self.topology.services:
            names.append(f"netlab-{s.group}-dnsmasq")
        return names

    def _tick(self) -> list[str]:
        actions: list[str] = []
        for name in self._expected():
            try:
                c = self._client.containers.get(name)
            except NotFound:
                logger.warning("%s: missing", name)
                actions.append(f"{name}: missing (manual recreate needed)")
                continue
            if c.status == "running":
                continue
            count = self._restarts.get(name, 0)
            if count >= self.max_restarts:
                logger.error(
                    "%s: giving up after %d restarts", name, count,
                )
                actions.append(f"{name}: gave up after {count} restarts")
                continue
            try:
                c.start()
                self._restarts[name] = count + 1
                logger.info(
                    "%s: restarted (attempt %d/%d)",
                    name, count + 1, self.max_restarts,
                )
                actions.append(f"{name}: restarted")
            except APIError as exc:
                logger.error("%s: restart failed: %s", name, exc)
                actions.append(f"{name}: restart failed: {exc}")
        return actions

    def run(self, max_iterations: int | None = None) -> None:
        print(
            f"Watching cluster '{self.topology.name}' "
            f"every {self.interval}s (max {self.max_restarts} restarts each)"
        )
        print("Press Ctrl-C to stop.")
        i = 0
        try:
            while max_iterations is None or i < max_iterations:
                self._tick()
                i += 1
                if max_iterations is None:
                    time.sleep(self.interval)
        except KeyboardInterrupt:
            print("\nWatcher stopped.")