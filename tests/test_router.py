"""Unit tests for RouterSpec and Router geometry."""
import pytest

from netlab.exceptions import ConfigurationError
from netlab.router import Router
from netlab.topology import GroupSpec, LabTopology, RouterSpec


class TestRouterSpec:
    def test_valid(self):
        RouterSpec(name="r1", connects=("a", "b")).validate()

    def test_single_group_rejected(self):
        with pytest.raises(ConfigurationError):
            RouterSpec(name="r1", connects=("a",)).validate()

    def test_bad_ip_suffix(self):
        with pytest.raises(ConfigurationError):
            RouterSpec(name="r1", connects=("a", "b"), ip_suffix=1).validate()

    def test_bad_ip_suffix_high(self):
        with pytest.raises(ConfigurationError):
            RouterSpec(name="r1", connects=("a", "b"), ip_suffix=255).validate()


class TestTopologyRouterValidation:
    def test_unknown_group(self):
        topo = LabTopology(
            groups=[GroupSpec(name="a", subnet="10.0.0.0/24", host_count=1)],
            routers=[RouterSpec(name="r1", connects=("a", "missing"))],
        )
        with pytest.raises(ConfigurationError):
            topo.validate()

    def test_duplicate_router(self):
        topo = LabTopology(
            groups=[
                GroupSpec(name="a", subnet="10.0.0.0/24", host_count=1),
                GroupSpec(name="b", subnet="10.1.0.0/24", host_count=1),
            ],
            routers=[
                RouterSpec(name="r1", connects=("a", "b")),
                RouterSpec(name="r1", connects=("a", "b")),
            ],
        )
        with pytest.raises(ConfigurationError):
            topo.validate()


class TestRouterIPs:
    def test_ip_computation(self):
        topo = LabTopology(
            groups=[
                GroupSpec(name="a", subnet="10.10.0.0/24", host_count=1),
                GroupSpec(name="b", subnet="10.20.0.0/24", host_count=1),
            ],
            routers=[RouterSpec(name="r1", connects=("a", "b"), ip_suffix=254)],
        )
        topo.validate()
        # Compute directly (Router needs Docker for deploy but _ip_for_group is pure)
        import docker
        try:
            client = docker.from_env()
        except Exception:
            pytest.skip("Docker not reachable")
        r = Router(spec=topo.routers[0], client=client,
                   topology=topo, cluster_name="t")
        assert r._ip_for_group("a") == "10.10.0.254"
        assert r._ip_for_group("b") == "10.20.0.254"
        assert r.host_default_gateway("a") == "10.10.0.254"