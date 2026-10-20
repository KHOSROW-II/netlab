"""Multi-group orchestration including routers and services."""
import logging

import docker

from .exceptions import ConfigurationError
from .firewall import FirewallManager, FirewallState, SYSCTL_KEY
from .group import Group
from .host_manager import HostManager
from .router import Router
from .services import DnsmasqService
from .topology import LabTopology, TopologyType

logger = logging.getLogger(__name__)


class Cluster:
    def __init__(self, topology: LabTopology) -> None:
        self.topology = topology
        self._client = docker.from_env()

    # ------------------------------------------------------------------ helpers

    def _make_group(self, group_name: str) -> Group:
        spec = self.topology.group(group_name)
        return Group(
            spec=spec, client=self._client,
            image=self.topology.image, cluster_name=self.topology.name,
        )

    def _make_router(self, router_spec) -> Router:
        return Router(
            spec=router_spec, client=self._client,
            topology=self.topology, cluster_name=self.topology.name,
        )

    def _make_service(self, service_spec) -> DnsmasqService:
        return DnsmasqService(
            spec=service_spec, client=self._client,
            topology=self.topology, cluster_name=self.topology.name,
        )

    # ------------------------------------------------------------------ deploy

    def deploy(self, allow_routing: bool = False) -> None:
        if allow_routing:
            self._ensure_routing_capable()
        self.destroy()
        for spec in self.topology.groups:
            self._make_group(spec.name).deploy()
        self._deploy_routers()
        self._apply_router_routes_to_hosts()
        self._deploy_services()
        logger.info(
            "Cluster %s deployed with %d groups, %d routers, %d services",
            self.topology.name, len(self.topology.groups),
            len(self.topology.routers), len(self.topology.services),
        )
        if allow_routing:
            self.firewall_install()

    def _ensure_routing_capable(self) -> None:
        if not any(len(r.connects) >= 2 for r in self.topology.routers):
            return
        fm = FirewallManager(self.topology)
        state = fm.state()
        if state.value == "1" and not state.can_change:
            hint = state.hint or (
                f"sudo sysctl -w {SYSCTL_KEY}=0 && "
                f"sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=0"
            )
            raise ConfigurationError(
                "Cannot deploy routers: br_netfilter is enabled and this "
                "process is not privileged. Cross-group routing requires "
                f"{SYSCTL_KEY}=0.\n"
                "Fix one of these ways, then re-deploy:\n"
                "  1) Restart the server as root:  sudo netlab web\n"
                "  2) Run the pre-flight fix once in a terminal:\n"
                f"     {hint}\n"
                "  3) Open the web UI and click the routing banner."
            )

    def _deploy_routers(self) -> None:
        for router_spec in self.topology.routers:
            try:
                self._make_router(router_spec).deploy()
            except Exception as exc:
                logger.error(
                    "Router %s failed to deploy: %s", router_spec.name, exc
                )
                raise

    def _apply_router_routes_to_hosts(self) -> None:
        host_mgr = HostManager(
            self._client, image=self.topology.image,
            label=self.topology.name,
        )
        for router_spec in self.topology.routers:
            router = self._make_router(router_spec)
            for group_name in router_spec.connects:
                gateway_ip = router.host_default_gateway(group_name)
                spec = self.topology.group(group_name)
                if spec.topology == TopologyType.RING:
                    logger.info(
                        "Skipping default-route injection for ring group %s",
                        group_name,
                    )
                    continue
                for idx in range(1, spec.host_count + 1):
                    host_name = f"netlab-{group_name}-host{idx}"
                    try:
                        host_mgr.set_default_route(host_name, gateway_ip)
                    except Exception as exc:
                        logger.warning(
                            "Could not route %s via %s: %s",
                            host_name, gateway_ip, exc,
                        )

    def _deploy_services(self) -> None:
        for svc_spec in self.topology.services:
            try:
                self._make_service(svc_spec).deploy()
            except Exception as exc:
                logger.error(
                    "Service %s on %s failed to deploy: %s",
                    svc_spec.type, svc_spec.group, exc,
                )

    # ------------------------------------------------------------------ destroy

    def destroy(self) -> None:
        """Remove containers and networks for this cluster.

        Also catches orphans that were created by older code without the
        netlab=<cluster> label, by matching the `netlab-<cluster>-` name
        prefix in addition to the label filter.
        """
        # 1. Containers by label
        try:
            containers = self._client.containers.list(
                all=True, filters={"label": f"netlab={self.topology.name}"}
            )
            for c in containers:
                try:
                    c.remove(force=True)
                except Exception as exc:
                    logger.warning("Could not remove %s: %s", c.name, exc)
        except Exception as exc:
            logger.warning("Container cleanup (label) failed: %s", exc)

        # 2. Containers by name prefix (orphans without labels)
        try:
            all_containers = self._client.containers.list(all=True)
            for c in all_containers:
                if not c.name.startswith("netlab-"):
                    continue
                # Skip containers belonging to a DIFFERENT cluster
                lbl = (c.labels or {}).get("netlab")
                if lbl and lbl != self.topology.name:
                    continue
                # Remove if it belongs to this cluster by name or label
                own_prefix = f"netlab-{self.topology.name}"
                if c.name == own_prefix or c.name.startswith(own_prefix + "-"):
                    try:
                        c.remove(force=True)
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("Container cleanup (prefix) failed: %s", exc)

        # 3. Networks by label
        try:
            networks = self._client.networks.list(
                filters={"label": f"netlab={self.topology.name}"}
            )
            for net in networks:
                try:
                    net.remove()
                except Exception as exc:
                    logger.warning(
                        "Could not remove network %s: %s", net.name, exc
                    )
        except Exception as exc:
            logger.warning("Network cleanup (label) failed: %s", exc)

        # 4. Networks by name prefix (orphans without labels)
        try:
            all_networks = self._client.networks.list()
            own_prefix = f"netlab-{self.topology.name}"
            for net in all_networks:
                if not net.name.startswith(own_prefix):
                    continue
                try:
                    net.remove()
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Network cleanup (prefix) failed: %s", exc)

    # ------------------------------------------------------------------ firewall

    def firewall_install(self) -> FirewallState:
        fm = FirewallManager(self.topology)
        if not fm.has_routers():
            logger.info("No routers; br_netfilter unchanged.")
            return fm.state()
        state = fm.install()
        if state.needs_change and not state.can_change:
            logger.warning(
                "br_netfilter is enabled (%s=1) but this process is not root. "
                "Cross-group routing will fail until you run:", SYSCTL_KEY,
            )
            for cmd in fm.persist_commands():
                logger.warning("  %s", cmd)
        elif state.value == "0":
            logger.info(
                "br_netfilter disabled; cross-group routing is enabled."
            )
        return state

    def firewall_status(self) -> None:
        fm = FirewallManager(self.topology)
        state = fm.state()
        print(f"Cluster      : {self.topology.name}")
        print(f"Routers      : {len(self.topology.routers)}")
        print(f"{SYSCTL_KEY} : {state.value}")
        print(f"Needs change : {state.needs_change}")
        if state.needs_change and not state.can_change:
            print()
            print("To enable cross-group routing, run:")
            for cmd in fm.persist_commands():
                print(f"  {cmd}")

    def firewall_revoke(self) -> FirewallState:
        return FirewallManager(self.topology).uninstall()

    # ------------------------------------------------------------------ host ops

    def _resolve_hosts(self, group_name: str, host_spec: str) -> list[str]:
        spec = self.topology.group(group_name)
        if host_spec == "all":
            indices = list(range(1, spec.host_count + 1))
        else:
            try:
                indices = [int(x) for x in host_spec.split(",")]
            except ValueError as exc:
                raise ConfigurationError(
                    f"Invalid host selector '{host_spec}'"
                ) from exc
        for idx in indices:
            if not (1 <= idx <= spec.host_count):
                raise ConfigurationError(
                    f"Host index {idx} out of range for group '{group_name}'"
                )
        return [f"netlab-{group_name}-host{i}" for i in indices]

    def exec(self, group_name: str, host_spec: str, cmd: list[str]) -> int:
        host_names = self._resolve_hosts(group_name, host_spec)
        group = self._make_group(group_name)
        overall = 0
        for host_name in host_names:
            print(f"[{host_name}] $ {' '.join(cmd)}")
            code, output = group.exec(host_name, cmd)
            if output:
                print(output.rstrip())
            if code != 0:
                print(f"[{host_name}] exit code {code}")
                overall = code
        return overall

    def set_dns(self, group_name: str, host_spec: str,
                servers: list[str],
                search_domains: list[str] | None = None) -> None:
        host_names = self._resolve_hosts(group_name, host_spec)
        group = self._make_group(group_name)
        for host_name in host_names:
            group.set_dns(host_name, servers, search_domains)
            print(f"[{host_name}] DNS updated")

    def set_ip(self, group_name: str, host_index: int, new_ip: str) -> None:
        spec = self.topology.group(group_name)
        if spec.topology == TopologyType.RING:
            raise ConfigurationError(
                "set-ip is not supported on ring topology groups"
            )
        host_name = f"netlab-{group_name}-host{host_index}"
        self._make_group(group_name).set_ip(host_name, new_ip)
        print(f"[{host_name}] IP updated to {new_ip}")

    # ------------------------------------------------------------------ status

    def status(self) -> None:
        containers = self._client.containers.list(
            all=True, filters={"label": f"netlab={self.topology.name}"}
        )
        by_group: dict[str, list] = {}
        for c in containers:
            group_name = c.labels.get("netlab.group")
            if group_name:
                by_group.setdefault(group_name, []).append(c)

        print(f"Cluster     : {self.topology.name}")
        print(f"Image       : {self.topology.image}")
        print(f"Groups      : {len(self.topology.groups)}")
        print(f"Routers     : {len(self.topology.routers)}")
        print(f"Services    : {len(self.topology.services)}")
        print("=" * 68)
        for spec in self.topology.groups:
            print(
                f"Group {spec.name} ({spec.subnet}, "
                f"{spec.topology.value}, {spec.host_count} hosts)"
            )
            cs = sorted(by_group.get(spec.name, []), key=lambda c: c.name)
            if not cs:
                print("  (no running containers)")
            for c in cs:
                nets = c.attrs.get("NetworkSettings", {}).get("Networks", {})
                ips = ", ".join(
                    f"{n}={d.get('IPAddress', '')}" for n, d in nets.items()
                )
                role = c.labels.get("netlab.role", "host")
                if c.labels.get("netlab.service"):
                    role += f":{c.labels['netlab.service']}"
                print(f"  {c.name:<32} {role:<16} {c.status:<10} {ips}")
            print()

        routers = [c for c in containers
                   if c.labels.get("netlab.role") == "router"]
        if routers:
            print("Routers:")
            for c in sorted(routers, key=lambda c: c.name):
                nets = c.attrs.get("NetworkSettings", {}).get("Networks", {})
                ips = ", ".join(
                    f"{n}={d.get('IPAddress', '')}" for n, d in nets.items()
                )
                print(f"  {c.name:<32} {c.status:<10} {ips}")