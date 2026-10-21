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
        self._deployed_routers = {}

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
        used_ips = {} 
        for router_spec in self.topology.routers:
            suffix_map = {}
            for net in router_spec.connects:
                net_name = f"netlab-{net}"
                if net_name not in used_ips:
                    used_ips[net_name] = set()
                suffix = router_spec.ip_suffix
                while suffix in used_ips[net_name]:
                    suffix -= 1
                used_ips[net_name].add(suffix)
                suffix_map[net] = suffix
            
            try:
                router = self._make_router(router_spec)
                router.deploy(suffix_map)
                self._deployed_routers[router_spec.name] = router
            except Exception as exc:
                logger.error("Router %s failed to deploy: %s", router_spec.name, exc)
                raise

    def _apply_router_routes_to_hosts(self) -> None:
        host_mgr = HostManager(self._client, image=self.topology.image, label=self.topology.name)
        for router_spec in self.topology.routers:
            router = self._deployed_routers.get(router_spec.name)
            if not router: continue
            for group_name in router_spec.connects:
                gateway_ip = router.host_default_gateway(group_name)
                spec = self.topology.group(group_name)
                if spec.topology == TopologyType.RING:
                    continue
                for idx in range(1, spec.host_count + 1):
                    host_name = f"netlab-{group_name}-host{idx}"
                    try:
                        host_mgr.set_default_route(host_name, gateway_ip)
                    except Exception as exc:
                        logger.warning("Could not route %s via %s: %s", host_name, gateway_ip, exc)

    def _deploy_services(self) -> None:
        for svc_spec in self.topology.services:
            try:
                self._make_service(svc_spec).deploy()
            except Exception as exc:
                logger.error("Service %s on %s failed: %s", svc_spec.type, svc_spec.group, exc)

    def destroy(self) -> None:
        self._deployed_routers = {}
        try:
            containers = self._client.containers.list(all=True, filters={"label": f"netlab={self.topology.name}"})
            for c in containers:
                try: c.remove(force=True)
                except Exception: pass
        except Exception: pass

        try:
            networks = self._client.networks.list(filters={"label": f"netlab={self.topology.name}"})
            for net in networks:
                try: net.remove()
                except Exception: pass
        except Exception: pass
        
        try:
            for c in self._client.containers.list(all=True):
                if c.name.startswith(f"netlab-{self.topology.name}-") or c.name == f"netlab-{self.topology.name}":
                    c.remove(force=True)
            for net in self._client.networks.list():
                if net.name.startswith(f"netlab-{self.topology.name}"):
                    net.remove()
        except Exception: pass

    def _resolve_hosts(self, group_name: str, host_spec: str) -> list[str]:
        spec = self.topology.group(group_name)
        if host_spec == "all":
            indices = list(range(1, spec.host_count + 1))
        else:
            try: indices = [int(x) for x in host_spec.split(",")]
            except ValueError as exc: raise ConfigurationError(f"Invalid host selector '{host_spec}'")
        for idx in indices:
            if not (1 <= idx <= spec.host_count):
                raise ConfigurationError(f"Host index {idx} out of range for group '{group_name}'")
        return [f"netlab-{group_name}-host{i}" for i in indices]

    def exec(self, group_name: str, host_spec: str, cmd: list[str]) -> int:
        host_names = self._resolve_hosts(group_name, host_spec)
        group = self._make_group(group_name)
        overall = 0
        for host_name in host_names:
            print(f"[{host_name}] $ {' '.join(cmd)}")
            code, output = group.exec(host_name, cmd)
            if output: print(output.rstrip())
            if code != 0:
                print(f"[{host_name}] exit code {code}")
                overall = code
        return overall

    def set_dns(self, group_name: str, host_spec: str, servers: list[str], search_domains: list[str] | None = None) -> None:
        host_names = self._resolve_hosts(group_name, host_spec)
        group = self._make_group(group_name)
        for host_name in host_names:
            group.set_dns(host_name, servers, search_domains)
            print(f"[{host_name}] DNS updated")

    def set_ip(self, group_name: str, host_index: int, new_ip: str) -> None:
        spec = self.topology.group(group_name)
        if spec.topology == TopologyType.RING:
            raise ConfigurationError("set-ip is not supported on ring topology groups")
        host_name = f"netlab-{group_name}-host{host_index}"
        self._make_group(group_name).set_ip(host_name, new_ip)
        print(f"[{host_name}] IP updated to {new_ip}")

    def firewall_install(self) -> FirewallState:
        fm = FirewallManager(self.topology)
        if not fm.has_routers(): return fm.state()
        return fm.install()

    def firewall_status(self) -> None:
        fm = FirewallManager(self.topology)
        state = fm.state()
        print(f"Cluster      : {self.topology.name}")
        print(f"Routers      : {len(self.topology.routers)}")
        print(f"{SYSCTL_KEY} : {state.value}")
        print(f"Needs change : {state.needs_change}")

    def firewall_revoke(self) -> FirewallState:
        return FirewallManager(self.topology).uninstall()

    def status(self) -> None:
        containers = self._client.containers.list(all=True, filters={"label": f"netlab={self.topology.name}"})
        by_group = {}
        for c in containers:
            group_name = c.labels.get("netlab.group")
            if group_name: by_group.setdefault(group_name, []).append(c)

        print(f"Cluster     : {self.topology.name}")
        print(f"Image       : {self.topology.image}")
        print(f"Groups      : {len(self.topology.groups)}")
        print(f"Routers     : {len(self.topology.routers)}")
        print(f"Services    : {len(self.topology.services)}")
        print("=" * 68)
        for spec in self.topology.groups:
            print(f"Group {spec.name} ({spec.subnet}, {spec.topology.value}, {spec.host_count} hosts)")
            cs = sorted(by_group.get(spec.name, []), key=lambda c: c.name)
            if not cs: print("  (no running containers)")
            for c in cs:
                nets = c.attrs.get("NetworkSettings", {}).get("Networks", {})
                ips = ", ".join(f"{n}={d.get('IPAddress', '')}" for n, d in nets.items())
                role = c.labels.get("netlab.role", "host")
                if c.labels.get("netlab.service"): role += f":{c.labels['netlab.service']}"
                print(f"  {c.name:<32} {role:<16} {c.status:<10} {ips}")
            print()

        routers = [c for c in containers if c.labels.get("netlab.role") == "router"]
        if routers:
            print("Routers:")
            for c in sorted(routers, key=lambda c: c.name):
                nets = c.attrs.get("NetworkSettings", {}).get("Networks", {})
                ips = ", ".join(f"{n}={d.get('IPAddress', '')}" for n, d in nets.items())
                print(f"  {c.name:<32} {c.status:<10} {ips}")