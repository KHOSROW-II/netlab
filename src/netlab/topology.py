"""Topology models and YAML loading."""
from dataclasses import dataclass, field
from enum import Enum
from ipaddress import IPv4Network
from pathlib import Path

import yaml

from .exceptions import ConfigurationError


class TopologyType(str, Enum):
    BUS = "bus"
    STAR = "star"
    RING = "ring"
    SWITCH = "switch"
    HUB = "hub"
    ACCESS_POINT = "access_point"


# Topology types that share a single Docker bridge with a placeholder
# device container (visible in `docker ps` and in the graph).
PLACEHOLDER_KINDS = {
    TopologyType.SWITCH: "switch",
    TopologyType.HUB: "hub",
    TopologyType.ACCESS_POINT: "ap",
}


@dataclass(frozen=True)
class GroupSpec:
    name: str
    subnet: str
    host_count: int
    start_offset: int = 10
    gateway_offset: int = 1
    dns_servers: tuple[str, ...] = ()
    search_domains: tuple[str, ...] = ()
    topology: TopologyType = TopologyType.BUS

    def validate(self) -> None:
        if not self.name or not self.name.replace("-", "").replace("_", "").isalnum():
            raise ConfigurationError(
                f"Invalid group name '{self.name}': use letters, digits, - or _"
            )
        try:
            IPv4Network(self.subnet, strict=False)
        except ValueError as exc:
            raise ConfigurationError(
                f"Group '{self.name}': invalid subnet '{self.subnet}': {exc}"
            ) from exc
        if self.host_count <= 0:
            raise ConfigurationError(
                f"Group '{self.name}': host_count must be > 0"
            )
        if self.topology == TopologyType.RING and self.host_count < 3:
            raise ConfigurationError(
                f"Group '{self.name}': ring topology requires at least 3 hosts"
            )
        if self.topology == TopologyType.RING and self.start_offset != 10:
            raise ConfigurationError(
                f"Group '{self.name}': start_offset is fixed for ring topology"
            )


@dataclass(frozen=True)
class RouterSpec:
    name: str
    connects: tuple[str, ...]
    ip_suffix: int = 254
    image: str = "nicolaka/netshoot:latest"

    def validate(self) -> None:
        if not self.name:
            raise ConfigurationError("Router name cannot be empty")
        if len(self.connects) < 2:
            raise ConfigurationError(
                f"Router '{self.name}' must connect to at least 2 groups"
            )
        if not (2 <= self.ip_suffix <= 254):
            raise ConfigurationError(
                f"Router '{self.name}': ip_suffix must be 2..254"
            )


@dataclass(frozen=True)
class ServiceSpec:
    type: str
    group: str
    ip_suffix: int = 250
    upstream: str = "8.8.8.8"
    dhcp_range: tuple[int, int] = (100, 200)

    def validate(self) -> None:
        if self.type not in ("dnsmasq",):
            raise ConfigurationError(
                f"Service '{self.type}' is not supported (use: dnsmasq)"
            )
        if not (2 <= self.ip_suffix <= 254):
            raise ConfigurationError(
                f"Service on '{self.group}': ip_suffix must be 2..254"
            )
        lo, hi = self.dhcp_range
        if not (2 < lo < hi <= 254):
            raise ConfigurationError(
                f"Service on '{self.group}': dhcp_range must satisfy "
                f"2 < lo < hi <= 254"
            )


@dataclass
class LabTopology:
    name: str = "netlab"
    image: str = "nicolaka/netshoot:latest"
    groups: list[GroupSpec] = field(default_factory=list)
    routers: list[RouterSpec] = field(default_factory=list)
    services: list[ServiceSpec] = field(default_factory=list)

    def validate(self) -> None:
        if not self.groups:
            raise ConfigurationError("Topology has no groups")
        names: set[str] = set()
        subnets: list[IPv4Network] = []
        for spec in self.groups:
            spec.validate()
            if spec.name in names:
                raise ConfigurationError(f"Duplicate group name: '{spec.name}'")
            names.add(spec.name)
            subnets.append(IPv4Network(spec.subnet, strict=False))
        for i in range(len(subnets)):
            for j in range(i + 1, len(subnets)):
                if subnets[i].overlaps(subnets[j]):
                    raise ConfigurationError(
                        f"Groups '{self.groups[i].name}' and "
                        f"'{self.groups[j].name}' have overlapping subnets"
                    )
        router_names: set[str] = set()
        for r in self.routers:
            r.validate()
            if r.name in router_names:
                raise ConfigurationError(f"Duplicate router name: '{r.name}'")
            router_names.add(r.name)
            for g in r.connects:
                if g not in names:
                    raise ConfigurationError(
                        f"Router '{r.name}' connects to unknown group '{g}'"
                    )
        for s in self.services:
            s.validate()
            if s.group not in names:
                raise ConfigurationError(
                    f"Service references unknown group '{s.group}'"
                )

    def group(self, name: str) -> GroupSpec:
        for spec in self.groups:
            if spec.name == name:
                return spec
        raise ConfigurationError(f"Unknown group: '{name}'")


def _normalize_group(data: dict) -> dict:
    data = dict(data)
    if "dns_servers" in data and isinstance(data["dns_servers"], list):
        data["dns_servers"] = tuple(str(x) for x in data["dns_servers"])
    if "search_domains" in data and isinstance(data["search_domains"], list):
        data["search_domains"] = tuple(str(x) for x in data["search_domains"])
    if "topology" in data and isinstance(data["topology"], str):
        data["topology"] = TopologyType(data["topology"].lower())
    return data


def _normalize_router(data: dict) -> dict:
    data = dict(data)
    if "connects" in data and isinstance(data["connects"], list):
        data["connects"] = tuple(str(x) for x in data["connects"])
    return data


def _normalize_service(data: dict) -> dict:
    data = dict(data)
    if "dhcp_range" in data and isinstance(data["dhcp_range"], list):
        data["dhcp_range"] = tuple(int(x) for x in data["dhcp_range"])
    return data


def load_topology(path: str | Path) -> LabTopology:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(
            f"Cannot read topology file '{path}': {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("Topology file must contain a mapping")
    topo = LabTopology(
        name=str(raw.get("name", "netlab")),
        image=str(raw.get("image", "nicolaka/netshoot:latest")),
        groups=[GroupSpec(**_normalize_group(g)) for g in raw.get("groups", [])],
        routers=[RouterSpec(**_normalize_router(r)) for r in raw.get("routers", [])],
        services=[ServiceSpec(**_normalize_service(s)) for s in raw.get("services", [])],
    )
    topo.validate()
    return topo