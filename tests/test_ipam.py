"""Unit tests for the IPAM module."""
import pytest

from netlab.exceptions import ConfigurationError
from netlab.ipam import (
    HostIPPlanner,
    IPv4Class,
    SubnetInfo,
    SubnetPlanner,
    analyze_ipv4,
    detect_ipv4_class,
    split_by_count,
    split_subnet,
    to_binary_ipv4,
    to_hex_ipv6,
)


class TestIPv4Class:
    def test_a(self):
        assert detect_ipv4_class("10.0.0.1") is IPv4Class.A
        assert detect_ipv4_class("1.1.1.1") is IPv4Class.A

    def test_b(self):
        assert detect_ipv4_class("128.0.0.1") is IPv4Class.B
        assert detect_ipv4_class("172.16.0.1") is IPv4Class.B

    def test_c(self):
        assert detect_ipv4_class("192.168.1.1") is IPv4Class.C

    def test_d(self):
        assert detect_ipv4_class("224.0.0.1") is IPv4Class.D

    def test_e(self):
        assert detect_ipv4_class("240.0.0.1") is IPv4Class.E


class TestSubnetInfo:
    def test_slash_24(self):
        info = SubnetInfo.from_cidr("10.10.0.0/24")
        assert info.total_addresses == 256
        assert info.usable_hosts == 254
        assert info.first_usable == "10.10.0.1"
        assert info.last_usable == "10.10.0.254"
        assert info.broadcast_address == "10.10.0.255"

    def test_slash_31(self):
        info = SubnetInfo.from_cidr("10.0.0.0/31")
        assert info.usable_hosts == 2

    def test_slash_32(self):
        info = SubnetInfo.from_cidr("10.0.0.1/32")
        assert info.usable_hosts == 1

    def test_ipv6(self):
        info = SubnetInfo.from_cidr("2001:db8::/64")
        assert info.total_addresses == 2**64
        assert info.broadcast_address is None


class TestSplit:
    def test_split_by_count(self):
        subnets = split_by_count("10.0.0.0/16", 4)
        assert len(subnets) == 4
        assert subnets[0].network.prefixlen == 18
        assert subnets[1].network.network_address.exploded == "10.0.64.0"

    def test_split_bad_prefix(self):
        with pytest.raises(ValueError):
            split_subnet("10.0.0.0/24", 16)

    def test_split_zero(self):
        with pytest.raises(ValueError):
            split_by_count("10.0.0.0/24", 0)


class TestHostIPPlanner:
    def test_default(self):
        p = HostIPPlanner("10.10.0.0/24", start_offset=10, gateway_offset=1)
        addrs = p.plan(5)
        assert [a.address for a in addrs] == [
            "10.10.0.10", "10.10.0.11", "10.10.0.12", "10.10.0.13", "10.10.0.14"
        ]
        assert p.gateway == "10.10.0.1"
        assert all(a.subnet == "10.10.0.0/24" for a in addrs)

    def test_gateway_conflict(self):
        with pytest.raises(ConfigurationError):
            HostIPPlanner("10.10.0.0/24", start_offset=1, gateway_offset=1)

    def test_overflow(self):
        p = HostIPPlanner("10.10.0.0/24", start_offset=250)
        with pytest.raises(ConfigurationError):
            p.plan(10)

    def test_broadcast_rejected(self):
        with pytest.raises(ConfigurationError):
            HostIPPlanner("10.10.0.0/24", start_offset=255)


class TestSubnetPlanner:
    def test_assign_groups(self):
        planner = SubnetPlanner("10.0.0.0/16")
        groups = planner.assign_to_groups(group_count=4, hosts_per_group=3)
        assert len(groups) == 4
        for subnet, hosts in groups:
            assert len(hosts) == 3
            assert subnet.network.prefixlen == 18


class TestAnalyze:
    def test_analyze_with_subnet(self):
        info = analyze_ipv4("10.10.0.10", "10.10.0.0/24")
        assert info.ip_class is IPv4Class.A
        assert len(info.network_bits) == 24
        assert len(info.host_bits) == 8
        assert info.address_in_subnet is True

    def test_analyze_outside_subnet(self):
        info = analyze_ipv4("10.0.0.1", "192.168.1.0/24")
        assert info.address_in_subnet is False


class TestDisplay:
    def test_binary(self):
        assert to_binary_ipv4("10.10.0.10") == (
            "00001010.00001010.00000000.00001010"
        )

    def test_hex_v6(self):
        assert to_hex_ipv6("2001:db8::1") == (
            "20010db8000000000000000000000001"
        )