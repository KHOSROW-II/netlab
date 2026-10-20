"""Image rendering via Netgraph + matplotlib (optional dependencies)."""
from ..exceptions import ConfigurationError
from ..topology import LabTopology
from .graph import build_graph


def render_image(
    topo: LabTopology,
    output_path: str,
    group: str | None = None,
) -> None:
    """Render the topology to a PNG/SVG file using Netgraph."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from netgraph import Graph as NetgraphGraph
    except ImportError as exc:
        raise ConfigurationError(
            "Image rendering requires optional dependencies. "
            "Install with: pip install -e '.[viz]'"
        ) from exc

    graph = build_graph(topo)
    if group is not None:
        nodes = [n for n, data in graph.nodes(data=True) if data["group"] == group]
        if not nodes:
            raise ConfigurationError(f"Unknown group: '{group}'")
        graph = graph.subgraph(nodes).copy()

    is_ring = any(
        data.get("kind") == "host" and graph.degree(n) == 2
        for n, data in graph.nodes(data=True)
    ) and not any(
        data.get("kind") in ("bus", "switch")
        for _, data in graph.nodes(data=True)
    )

    node_color = {}
    for node, data in graph.nodes(data=True):
        kind = data.get("kind", "host")
        node_color[node] = {
            "host": "#4ECDC4",
            "bus": "#FF6B6B",
            "switch": "#95A5A6",
        }.get(kind, "#CCCCCC")

    labels = {n: data.get("label", n) for n, data in graph.nodes(data=True)}

    fig, ax = plt.subplots(figsize=(10, 7))
    NetgraphGraph(
        graph,
        node_labels=labels,
        node_color=node_color,
        node_edge_color="#222222",
        node_size=12.0,
        node_layout="circular" if is_ring else "spring",
        node_layout_kwargs={"seed": 42},
        edge_color="#555555",
        ax=ax,
    )
    fig.savefig(output_path, dpi=140, bbox_inches="tight")
    plt.close(fig)