"""Unit tests for Phase 3 topology parsing and validation."""
import pytest

from netlab.exceptions import ConfigurationError
from netlab.topology import (
    GroupSpec,
    LabTopology,
    TopologyType,
    load_topology,
)


def _write(tmp_path, content):
    p = tmp_path / "topo.yaml"
    p.write_text(content)
    return p


class TestGroupSpec:
    def test_valid_bus(self):
        GroupSpec(name="g", subnet="10.0.0.0/24", host_count=3).validate()

    def test_ring_requires_three(self):
        with pytest.raises(ConfigurationError):
            GroupSpec(
                name="g", subnet="10.0.0.0/24",
                host_count=2, topology=TopologyType.RING,
            ).validate()

    def test_ring_requires_fixed_offset(self):
        with pytest.raises(ConfigurationError):
            GroupSpec(
                name="g", subnet="10.0.0.0/24",
                host_count=3, start_offset=20, topology=TopologyType.RING,
            ).validate()

    def test_bad_subnet(self):
        with pytest.raises(ConfigurationError):
            GroupSpec(name="g", subnet="not-a-cidr", host_count=2).validate()

    def test_zero_hosts(self):
        with pytest.raises(ConfigurationError):
            GroupSpec(name="g", subnet="10.0.0.0/24", host_count=0).validate()


class TestLabTopology:
    def test_duplicate_names(self):
        topo = LabTopology(
            name="t",
            groups=[
                GroupSpec(name="a", subnet="10.0.0.0/24", host_count=1),
                GroupSpec(name="a", subnet="10.1.0.0/24", host_count=1),
            ],
        )
        with pytest.raises(ConfigurationError):
            topo.validate()

    def test_overlapping_subnets(self):
        topo = LabTopology(
            name="t",
            groups=[
                GroupSpec(name="a", subnet="10.0.0.0/16", host_count=1),
                GroupSpec(name="b", subnet="10.0.1.0/24", host_count=1),
            ],
        )
        with pytest.raises(ConfigurationError):
            topo.validate()

    def test_empty(self):
        with pytest.raises(ConfigurationError):
            LabTopology(name="t", groups=[]).validate()

    def test_lookup(self):
        topo = LabTopology(
            name="t",
            groups=[GroupSpec(name="a", subnet="10.0.0.0/24", host_count=1)],
        )
        assert topo.group("a").name == "a"
        with pytest.raises(ConfigurationError):
            topo.group("missing")


class TestLoadYaml:
    def test_basic(self, tmp_path):
        path = _write(tmp_path, """
name: demo
groups:
  - name: g1
    subnet: 10.10.0.0/24
    host_count: 3
    dns_servers: ["8.8.8.8"]
    topology: bus
""")
        topo = load_topology(path)
        assert topo.name == "demo"
        assert topo.groups[0].dns_servers == ("8.8.8.8",)
        assert topo.groups[0].topology is TopologyType.BUS

    def test_invalid_file(self, tmp_path):
        path = _write(tmp_path, "not: a: valid: yaml: file")
        with pytest.raises(ConfigurationError):
            load_topology(path)

    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigurationError):
            load_topology(tmp_path / "missing.yaml")

    def test_ring_parsing(self, tmp_path):
        path = _write(tmp_path, """
name: demo
groups:
  - name: ringA
    subnet: 10.0.0.0/24
    host_count: 3
    topology: ring
""")
        topo = load_topology(path)
        assert topo.groups[0].topology is TopologyType.RING