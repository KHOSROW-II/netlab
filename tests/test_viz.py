"""Unit tests for Phase 4 visualization."""
import pytest

from netlab.topology import GroupSpec, LabTopology, TopologyType
from netlab.viz import build_graph, render_ascii, to_dot
from netlab.viz.render import render_image


def _topo(topology_type, host_count, subnet="10.10.0.0/24"):
    return LabTopology(
        name="t",
        groups=[
            GroupSpec(
                name="g1", subnet=subnet, host_count=host_count,
                topology=topology_type,
            )
        ],
    )


class TestBuildGraph:
    def test_bus(self):
        g = build_graph(_topo(TopologyType.BUS, 3))
        assert g.number_of_nodes() == 4
        assert g.number_of_edges() == 3
        assert any(d.get("kind") == "bus" for _, d in g.nodes(data=True))
        assert sum(1 for _, d in g.nodes(data=True) if d.get("kind") == "host") == 3

    def test_star(self):
        g = build_graph(_topo(TopologyType.STAR, 4))
        assert g.number_of_nodes() == 5
        assert any(d.get("kind") == "switch" for _, d in g.nodes(data=True))

    def test_ring(self):
        g = build_graph(_topo(TopologyType.RING, 3))
        assert g.number_of_nodes() == 3
        assert g.number_of_edges() == 3
        ring_edges = [d for _, _, d in g.edges(data=True)]
        assert all("link" in e for e in ring_edges)

    def test_multiple_groups(self):
        topo = LabTopology(groups=[
            GroupSpec(name="a", subnet="10.0.0.0/24", host_count=2),
            GroupSpec(name="b", subnet="10.1.0.0/24", host_count=3),
        ])
        g = build_graph(topo)
        # group a: 2 hosts + 1 bus = 3; group b: 3 hosts + 1 bus = 4
        assert g.number_of_nodes() == 7


class TestASCII:
    def test_bus_contains_ips(self):
        text = render_ascii(_topo(TopologyType.BUS, 2))
        assert "10.10.0.10" in text
        assert "10.10.0.11" in text
        assert "bus" in text
        assert "host1" in text and "host2" in text

    def test_ring_contains_link_names(self):
        text = render_ascii(_topo(TopologyType.RING, 3))
        for name in ("net0", "net1", "net2"):
            assert name in text

    def test_group_filter(self):
        topo = LabTopology(groups=[
            GroupSpec(name="g1", subnet="10.0.0.0/24", host_count=2),
            GroupSpec(name="g2", subnet="10.1.0.0/24", host_count=2),
        ])
        text = render_ascii(topo, group="g1")
        assert "g1" in text
        assert "g2" not in text


class TestDOT:
    def test_structure(self):
        text = to_dot(_topo(TopologyType.BUS, 2))
        assert text.startswith("digraph netlab")
        assert "subgraph cluster_g1" in text
        assert "host1" in text
        assert "->" in text

    def test_ring_uses_undirected_edges(self):
        text = to_dot(_topo(TopologyType.RING, 3))
        assert "[dir=none" in text


class TestExample:
    def test_write_example(self, tmp_path):
        from netlab.examples import write_example
        target = tmp_path / "nested" / "dir" / "topo.yaml"
        write_example(str(target))
        assert target.exists()
        content = target.read_text()
        assert "groups:" in content
        assert "grpA" in content


class TestRenderImage:
    def test_render_creates_file(self, tmp_path):
        pytest.importorskip("netgraph")
        pytest.importorskip("matplotlib")
        out = tmp_path / "graph.png"
        render_image(_topo(TopologyType.BUS, 2), str(out))
        assert out.exists()
        assert out.stat().st_size > 0