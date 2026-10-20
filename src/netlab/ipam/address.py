"""IPv4 address classification."""
from enum import Enum
from ipaddress import IPv4Address


class IPv4Class(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


def detect_ipv4_class(address: IPv4Address | str) -> IPv4Class:
    """Classify an IPv4 address into A/B/C/D/E by its first octet."""
    ip = IPv4Address(str(address))
    first = int(str(ip).split(".")[0])
    if 0 <= first <= 127:
        return IPv4Class.A
    if 128 <= first <= 191:
        return IPv4Class.B
    if 192 <= first <= 223:
        return IPv4Class.C
    if 224 <= first <= 239:
        return IPv4Class.D
    if 240 <= first <= 255:
        return IPv4Class.E
    raise ValueError(f"Cannot classify IPv4 address {address}")


def default_prefix_for_class(ip_class: IPv4Class) -> int | None:
    """Return the classful prefix length, or None for D/E (no classful prefix)."""
    return {
        IPv4Class.A: 8,
        IPv4Class.B: 16,
        IPv4Class.C: 24,
        IPv4Class.D: None,
        IPv4Class.E: None,
    }[ip_class]