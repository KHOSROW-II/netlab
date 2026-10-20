"""IP address management: classification, subnetting, planning, analysis."""

from .address import IPv4Class, default_prefix_for_class, detect_ipv4_class
from .display import (
    IPv4Analysis,
    IPv6Analysis,
    analyze_ipv4,
    analyze_ipv6,
    to_binary_ipv4,
    to_hex_ipv6,
)
from .planner import HostAddress, HostIPPlanner, SubnetPlanner
from .subnet import SubnetInfo, split_by_count, split_subnet

__all__ = [
    "IPv4Class",
    "default_prefix_for_class",
    "detect_ipv4_class",
    "IPv4Analysis",
    "IPv6Analysis",
    "analyze_ipv4",
    "analyze_ipv6",
    "to_binary_ipv4",
    "to_hex_ipv6",
    "HostAddress",
    "HostIPPlanner",
    "SubnetPlanner",
    "SubnetInfo",
    "split_by_count",
    "split_subnet",
]