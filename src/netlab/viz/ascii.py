"""ASCII/Unicode rendering of a LabTopology for the terminal."""
from ..ipam import HostIPPlanner, split_by_count
from ..topology import GroupSpec, LabTopology, TopologyType


def render_ascii(topo: LabTopology, group: str | None = None) -> str:
    """Return a terminal-friendly text rendering of the topology."""
    lines: list[str] = []
    lines.append(f"Cluster : {topo.name}")
    lines.append(f"Image   : {topo.image}")
    lines.append(f"Groups  : {len(topo.groups)}")
    lines.append("=" * 64)
    for spec in topo.groups:
        if group is not None and spec.name != group:
            continue
        lines.append("")
        if spec.topology == TopologyType.RING:
            lines.extend(_ring(spec))
        else:
            lines.extend(_hub_spoke(spec))
    return "\n".join(lines)


def _hub_spoke(spec: GroupSpec) -> list[str]:
    planner = HostIPPlanner(
        cidr=spec.subnet,
        start_offset=spec.start_offset,
        gateway_offset=spec.gateway_offset,
    )
    assignments = planner.plan(spec.host_count)
    hub_kind = "bus" if spec.topology == TopologyType.BUS else "switch"
    out: list[str] = []
    out.append(f"Group : {spec.name}")
    out.append(f"  Subnet  : {spec.subnet}")
    out.append(f"  Type    : {spec.topology.value}")
    out.append(f"  Gateway : {planner.gateway}")
    out.append(f"  Hosts   : {spec.host_count}")
    out.append("  Hosts:")
    for idx, addr in enumerate(assignments, start=1):
        out.append(f"    host{idx:<3} {addr.address}")
    out.append("  Links:")
    for idx in range(1, spec.host_count + 1):
        out.append(f"    host{idx} <-> {hub_kind} ({planner.gateway})")
    return out


def _ring(spec: GroupSpec) -> list[str]:
    n = spec.host_count
    pair_subnets = split_by_count(spec.subnet, n)[:n]
    out: list[str] = []
    out.append(f"Group : {spec.name}")
    out.append(f"  Subnet  : {spec.subnet}")
    out.append(f"  Type    : {spec.topology.value}")
    out.append(f"  Hosts   : {spec.host_count}")
    out.append("  Hosts (each host has two interfaces):")
    for i in range(n):
        left_idx = (i - 1) % n
        right_idx = i
        left_ip = str(pair_subnets[left_idx].network.network_address + 11)
        right_ip = str(pair_subnets[right_idx].network.network_address + 10)
        out.append(
            f"    host{i + 1:<3} net{left_idx}={left_ip:<15} "
            f"net{right_idx}={right_ip}"
        )
    out.append("  Links:")
    for i in range(n):
        a = i + 1
        b = ((i + 1) % n) + 1
        out.append(f"    host{a} --[net{i}]-- host{b}")
    return out