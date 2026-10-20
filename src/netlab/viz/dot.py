"""Graphviz DOT rendering."""
from ..topology import LabTopology


def to_dot(topo: LabTopology) -> str:
    """Return the topology as Graphviz DOT source."""
    lines: list[str] = ["digraph netlab {", "  rankdir=LR;"]
    lines.append(f'  graph [label="{topo.name}", labelloc=t];')
    for spec in topo.groups:
        lines.append(f"  subgraph cluster_{spec.name} {{")
        lines.append(
            f'    label="{spec.name}\\n({spec.topology.value}, {spec.subnet})";'
        )
        if spec.topology.value == "ring":
            lines.extend(_dot_ring(spec))
        else:
            lines.extend(_dot_hub(spec))
        lines.append("  }")
    lines.append("}")
    return "\n".join(lines)


def _dot_hub(spec) -> list[str]:
    from ..ipam import HostIPPlanner
    planner = HostIPPlanner(
        cidr=spec.subnet,
        start_offset=spec.start_offset,
        gateway_offset=spec.gateway_offset,
    )
    hub_id = f"{spec.name}__hub"
    hub_label = "bus" if spec.topology.value == "bus" else "switch"
    out: list[str] = [
        f'    "{hub_id}" [shape=box, style=filled, fillcolor="#3498db", '
        f'label="{hub_label}\\n{planner.gateway}"];'
    ]
    for idx, addr in enumerate(planner.plan(spec.host_count), start=1):
        host_id = f"{spec.name}__host{idx}"
        out.append(
            f'    "{host_id}" [shape=ellipse, style=filled, fillcolor="#4ecdc4", '
            f'label="host{idx}\\n{addr.address}"];'
        )
        out.append(f'    "{host_id}" -> "{hub_id}";')
    return out


def _dot_ring(spec) -> list[str]:
    n = spec.host_count
    out: list[str] = []
    for idx in range(1, n + 1):
        host_id = f"{spec.name}__host{idx}"
        out.append(
            f'    "{host_id}" [shape=ellipse, style=filled, fillcolor="#4ecdc4", '
            f'label="host{idx}"];'
        )
    for i in range(n):
        a = f"{spec.name}__host{i + 1}"
        b = f"{spec.name}__host{((i + 1) % n) + 1}"
        out.append(f'    "{a}" -> "{b}" [dir=none, label="net{i}"];')
    return out