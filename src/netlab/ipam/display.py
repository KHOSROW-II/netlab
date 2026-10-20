"""Binary/hex rendering and step-by-step address analysis."""
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network

from .address import IPv4Class, default_prefix_for_class, detect_ipv4_class
from .subnet import SubnetInfo


def to_binary_ipv4(address: str) -> str:
    """Render an IPv4 address as dotted binary octets."""
    bits = format(int(IPv4Address(address)), "032b")
    return ".".join(bits[i : i + 8] for i in range(0, 32, 8))


def to_hex_ipv6(address: str) -> str:
    """Render an IPv6 address as a 32-character lowercase hex string."""
    return format(int(IPv6Address(address)), "032x")


def _binary_bits(address: str) -> str:
    return format(int(IPv4Address(address)), "032b")


@dataclass(frozen=True)
class IPv4Analysis:
    address: str
    subnet: str
    ip_class: IPv4Class | None
    prefix_length: int
    netmask: str
    host_bits_count: int
    binary_address: str
    binary_netmask: str
    binary_network: str
    binary_broadcast: str
    network_bits: str
    host_bits: str
    network_address: str
    broadcast_address: str
    first_usable: str
    last_usable: str
    total_addresses: int
    usable_hosts: int
    address_in_subnet: bool


def analyze_ipv4(address: str, subnet: str | None = None) -> IPv4Analysis:
    """Produce a step-by-step breakdown of an IPv4 address."""
    ip = IPv4Address(address)

    if subnet is None:
        try:
            ip_class = detect_ipv4_class(ip)
        except ValueError as exc:
            raise ValueError(f"Cannot analyze address {address}: {exc}") from exc
        prefix = default_prefix_for_class(ip_class)
        if prefix is None:
            raise ValueError(
                f"Class {ip_class.value} has no classful prefix; "
                f"provide --subnet explicitly"
            )
        network = IPv4Network(f"{ip}/{prefix}", strict=False)
    else:
        network = IPv4Network(subnet, strict=False)
        try:
            ip_class = detect_ipv4_class(ip)
        except ValueError:
            ip_class = None

    info = SubnetInfo.from_cidr(network)
    full_bits = _binary_bits(ip)

    return IPv4Analysis(
        address=str(ip),
        subnet=str(network),
        ip_class=ip_class,
        prefix_length=network.prefixlen,
        netmask=str(network.netmask),
        host_bits_count=32 - network.prefixlen,
        binary_address=to_binary_ipv4(str(ip)),
        binary_netmask=to_binary_ipv4(str(network.netmask)),
        binary_network=to_binary_ipv4(str(network.network_address)),
        binary_broadcast=to_binary_ipv4(str(network[-1])),
        network_bits=full_bits[: network.prefixlen],
        host_bits=full_bits[network.prefixlen :],
        network_address=str(network.network_address),
        broadcast_address=str(network[-1]),
        first_usable=info.first_usable,
        last_usable=info.last_usable,
        total_addresses=info.total_addresses,
        usable_hosts=info.usable_hosts,
        address_in_subnet=ip in network,
    )


@dataclass(frozen=True)
class IPv6Analysis:
    address: str
    subnet: str
    prefix_length: int
    host_bits_count: int
    hex_address: str
    network_address: str
    last_address: str
    interface_id: str
    address_in_subnet: bool


def analyze_ipv6(address: str, subnet: str | None = None) -> IPv6Analysis:
    """Produce a summary analysis of an IPv6 address."""
    ip = IPv6Address(address)
    network = IPv6Network(subnet, strict=False) if subnet else IPv6Network(
        f"{ip}/64", strict=False
    )
    full_hex = to_hex_ipv6(str(ip))
    interface_id = full_hex[-16:] if network.prefixlen <= 64 else ""
    return IPv6Analysis(
        address=str(ip),
        subnet=str(network),
        prefix_length=network.prefixlen,
        host_bits_count=128 - network.prefixlen,
        hex_address=full_hex,
        network_address=str(network.network_address),
        last_address=str(network[-1]),
        interface_id=interface_id,
        address_in_subnet=ip in network,
    )