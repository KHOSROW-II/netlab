"""Unit tests for ServiceSpec and dnsmasq config generation."""
import pytest

from netlab.exceptions import ConfigurationError
from netlab.topology import GroupSpec, LabTopology, ServiceSpec


class TestServiceSpec:
    def test_valid(self):
        ServiceSpec(type="dnsmasq", group="g", ip_suffix=250).validate()

    def test_unknown_type(self):
        with pytest.raises(ConfigurationError):
            ServiceSpec(type="bind", group="g").validate()

    def test_dhcp_range_bad(self):
        with pytest.raises(ConfigurationError):
            ServiceSpec(
                type="dnsmasq", group="g", dhcp_range=(200, 100)
            ).validate()


class TestDnsmasqConfig:
    def test_config_has_no_interface_directive(self):
        topo = LabTopology(
            groups=[GroupSpec(name="g", subnet="10.0.0.0/24", host_count=1)],
            services=[ServiceSpec(type="dnsmasq", group="g",
                                  ip_suffix=250,
                                  upstream="9.9.9.9",
                                  dhcp_range=(100, 200))],
        )
        topo.validate()
        from netlab.services import DnsmasqService
        import docker
        try:
            client = docker.from_env()
        except Exception:
            pytest.skip("Docker not reachable")
        svc = DnsmasqService(
            spec=topo.services[0], client=client,
            topology=topo, cluster_name="t",
        )
        cfg = svc._build_config()
        # must NOT bind to a specific interface
        assert "interface=eth0" not in cfg
        assert "interface=" not in cfg
        # must use bind-dynamic so eth1 appears later
        assert "bind-dynamic" in cfg
        # must log to stdout for docker logs to work
        assert "log-facility=-" in cfg
        # must still serve the expected DNS/DHCP
        assert "server=9.9.9.9" in cfg
        assert "dhcp-range=10.0.0.100,10.0.0.200" in cfg
        assert "dns-server,10.0.0.250" in cfg