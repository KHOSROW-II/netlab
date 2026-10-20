"""Subnet calculation utilities for IPv4 and IPv6."""
from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network, ip_network

Network = IPv4Network | IPv6Network


@dataclass(frozen=True)
class SubnetInfo:
    """Immutable summary of a subnet."""

    network: Network
    network_address: str
    last_address: str
    broadcast_address: str | None  # None for IPv6
    first_usable: str
    last_usable: str
    total_addresses: int
    usable_hosts: int
    prefix_length: int
    netmask: str
    host_bits: int

    @classmethod
    def from_cidr(cls, cidr: str | Network) -> "SubnetInfo":
        network = ip_network(str(cidr), strict=False)
        total = network.num_addresses
        last_addr = network[-1]

        if network.version == 4:
            if network.prefixlen < 31:
                usable = max(0, total - 2)
                first = network.network_address + 1
                last = network.network_address + total - 2
            else:
                usable = total
                first = network.network_address
                last = last_addr
            broadcast: str | None = str(last_addr)
        else:
            usable = total
            first = network.network_address
            last = last_addr
            broadcast = None

        return cls(
            network=network,
            network_address=str(network.network_address),
            last_address=str(last_addr),
            broadcast_address=broadcast,
            first_usable=str(first),
            last_usable=str(last),
            total_addresses=total,
            usable_hosts=usable,
            prefix_length=network.prefixlen,
            netmask=str(network.netmask),
            host_bits=network.max_prefixlen - network.prefixlen,
        )


def split_subnet(cidr: str | Network, new_prefix: int) -> list[SubnetInfo]:
    """Split a subnet into equally-sized subnets of the given prefix."""
    network = ip_network(str(cidr), strict=False)
    if new_prefix < network.prefixlen:
        raise ValueError(
            f"Cannot split /{network.prefixlen} into /{new_prefix}"
        )
    if new_prefix > network.max_prefixlen:
        raise ValueError(
            f"Prefix /{new_prefix} exceeds maximum /{network.max_prefixlen}"
        )
    return [SubnetInfo.from_cidr(s) for s in network.subnets(new_prefix=new_prefix)]


def split_by_count(cidr: str | Network, count: int) -> list[SubnetInfo]:
    """Split a subnet into at least `count` equally-sized subnets."""
    if count <= 0:
        raise ValueError("count must be positive")
    network = ip_network(str(cidr), strict=False)
    for new_prefix in range(network.prefixlen, network.max_prefixlen + 1):
        if 2 ** (new_prefix - network.prefixlen) >= count:
            return split_subnet(cidr, new_prefix)
    raise ValueError(f"Cannot split {network} into {count} subnets")