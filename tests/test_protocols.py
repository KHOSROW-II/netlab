"""Unit tests for protocol simulators."""
import pytest

from netlab.protocols import (
    ARPSimulator,
    DHCPSimulator,
    DNSSimulator,
    ICMPSimulator,
    ProtocolEvent,
    render_summary,
    render_timeline,
)
from netlab.topology import GroupSpec, LabTopology


@pytest.fixture
def topo():
    return LabTopology(
        name="t",
        groups=[
            GroupSpec(name="g1", subnet="10.10.0.0/24", host_count=3),
        ],
    )


class TestProtocolEvent:
    def test_frozen(self):
        e = ProtocolEvent(
            step=1, layer="L3", protocol="ICMP",
            src="a", dst="b", info="x",
        )
        with pytest.raises(Exception):
            e.step = 2  # frozen dataclass


class TestARPSimulator:
    def test_sequence(self, topo):
        events = ARPSimulator(topo, "g1", src_idx=1, dst_idx=2).run()
        assert len(events) >= 6
        # first event is the ping request that triggers ARP
        assert events[0].protocol == "ICMP"
        # there is at least one ARP broadcast
        broadcasts = [e for e in events if e.protocol == "ARP"
                      and "WHO-HAS" in e.info]
        assert len(broadcasts) == 1
        # ends with ICMP reply
        assert events[-1].protocol == "ICMP"
        assert "reply" in events[-1].info.lower()

    def test_ips_match_planner(self, topo):
        events = ARPSimulator(topo, "g1", src_idx=1, dst_idx=3).run()
        broadcast = next(e for e in events if "WHO-HAS" in e.info)
        assert "10.10.0.12" in broadcast.info  # dst_idx=3
        assert "10.10.0.10" in broadcast.info  # src_idx=1


class TestICMPSimulator:
    def test_sequence(self, topo):
        events = ICMPSimulator(topo, "g1", src_idx=1, dst_idx=2).run()
        assert any("echo request" in e.info for e in events)
        assert any("echo reply" in e.info for e in events)
        assert all(e.protocol == "ICMP" for e in events)


class TestDNSSimulator:
    def test_query_contains_name(self, topo):
        events = DNSSimulator(topo, "g1", src_idx=1,
                              query="test.example").run()
        assert any("test.example" in e.info for e in events)
        # first event is a query, last is the resolution notification
        assert "query" in events[0].info.lower()
        assert "example" in events[-1].info or "connect" in events[-1].info


class TestDHCPSimulator:
    def test_dora_present(self, topo):
        events = DHCPSimulator(topo, "g1", src_idx=1).run()
        joined = " ".join(e.info for e in events)
        for keyword in ("DISCOVER", "OFFER", "REQUEST", "ACK"):
            assert keyword in joined, f"missing {keyword}"


class TestPresenter:
    def test_timeline_format(self):
        events = [
            ProtocolEvent(1, "L3", "ICMP", "10.0.0.1", "10.0.0.2",
                          "echo request"),
            ProtocolEvent(2, "L3", "ICMP", "10.0.0.2", "10.0.0.1",
                          "echo reply"),
        ]
        text = render_timeline(events)
        assert "ICMP" in text
        assert "10.0.0.1" in text
        assert "echo request" in text
        assert "echo reply" in text

    def test_timeline_empty(self):
        assert "(no events)" in render_timeline([])

    def test_summary(self):
        events = [
            ProtocolEvent(1, "L3", "ICMP", "a", "b", "x"),
            ProtocolEvent(2, "L2", "ARP", "a", "b", "y"),
            ProtocolEvent(3, "L3", "ICMP", "a", "b", "z"),
        ]
        text = render_summary(events)
        assert "Total events : 3" in text
        assert "ICMP=2" in text
        assert "ARP=1" in text