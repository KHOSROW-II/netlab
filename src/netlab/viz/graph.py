"""Build a NetworkX graph from a LabTopology."""
from ipaddress import IPv4Network

import networkx as nx

from ..ipam import HostIPPlanner, split_by_count
from ..topology import GroupSpec, LabTopology, TopologyType


def build_graph(topo: LabTopology) -> nx.Graph:
    """Return a NetworkX graph representation of the whole cluster."""
    graph = nx.Graph()
    graph.graph["name"] = topo.name
    graph.graph["image"] = topo.image
    for spec in topo.groups:
        if spec.topology == TopologyType.RING:
            _add_ring(graph, spec)
        else:
            hub_kind = "bus" if spec.topology == TopologyType.BUS else "switch"
            _add_hub_spoke(graph, spec, hub_kind)
    return graph


def _add_hub_spoke(graph: nx.Graph, spec: GroupSpec, hub_kind: str) -> None:
    planner = HostIPPlanner(
        cidr=spec.subnet,
        start_offset=spec.start_offset,
        gateway_offset=spec.gateway_offset,
    )
    hub_id = f"{spec.name}::{hub_kind}"
    graph.add_node(
        hub_id,
        kind=hub_kind,
        group=spec.name,
        gateway=planner.gateway,
        label=f"{hub_kind}\n{planner.gateway}",
    )
    for idx, addr in enumerate(
        planner.plan(spec.host_count), start=1
    ):
        host_id = f"{spec.name}::host{idx}"
        graph.add_node(
            host_id,
            kind="host",
            group=spec.name,
            ip=addr.address,
            label=f"host{idx}\n{addr.address}",
        )
        graph.add_edge(host_id, hub_id, link="")


def _add_ring(graph: nx.Graph, spec: GroupSpec) -> None:
    n = spec.host_count
    pair_subnets = split_by_count(spec.subnet, n)[:n]
    for idx in range(1, n + 1):
        host_id = f"{spec.name}::host{idx}"
        graph.add_node(
            host_id,
            kind="host",
            group=spec.name,
            label=f"host{idx}",
        )
    for i in range(n):
        host_a = f"{spec.name}::host{i + 1}"
        host_b = f"{spec.name}::host{((i + 1) % n) + 1}"
        graph.add_edge(
            host_a,
            host_b,
            link=f"net{i}",
            subnet=str(pair_subnets[i].network),
        )