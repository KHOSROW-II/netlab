"""Host IP planning and hierarchical subnet planning."""
from dataclasses import dataclass, field

from ..exceptions import ConfigurationError
from .subnet import SubnetInfo, split_by_count


@dataclass(frozen=True)
class HostAddress:
    """A static IP assignment for one host."""

    index: int
    address: str
    subnet: str
    gateway: str
    dns_servers: tuple[str, ...] = field(default_factory=tuple)
    search_domains: tuple[str, ...] = field(default_factory=tuple)


class HostIPPlanner:
    """Assign static IPs to hosts within a subnet."""

    def __init__(
        self,
        cidr: str,
        start_offset: int = 10,
        gateway_offset: int = 1,
    ) -> None:
        self.info = SubnetInfo.from_cidr(cidr)
        self.start_offset = start_offset
        self.gateway_offset = gateway_offset
        self._validate()

    def _validate(self) -> None:
        if self.start_offset < 0:
            raise ConfigurationError("start_offset must be non-negative")
        if self.gateway_offset < 0:
            raise ConfigurationError("gateway_offset must be non-negative")
        if self.start_offset == self.gateway_offset:
            raise ConfigurationError(
                f"start_offset ({self.start_offset}) must differ from "
                f"gateway_offset ({self.gateway_offset})"
            )
        network = self.info.network
        if network.version == 4 and network.prefixlen < 31:
            if self.start_offset == 0:
                raise ConfigurationError(
                    "start_offset 0 is reserved for the network address"
                )
            if self.gateway_offset == 0:
                raise ConfigurationError(
                    "gateway_offset 0 is reserved for the network address"
                )
            if self.start_offset >= self.info.total_addresses - 1:
                raise ConfigurationError(
                    "start_offset falls on or beyond the broadcast address"
                )
            if self.gateway_offset >= self.info.total_addresses - 1:
                raise ConfigurationError(
                    "gateway_offset falls on or beyond the broadcast address"
                )

    @property
    def gateway(self) -> str:
        return str(self.info.network.network_address + self.gateway_offset)

    def plan(self, count: int) -> list[HostAddress]:
        """Return `count` host assignments starting at start_offset."""
        if count <= 0:
            raise ConfigurationError("count must be positive")

        network = self.info.network
        if network.version == 4 and network.prefixlen < 31:
            max_offset = self.info.total_addresses - 2
        else:
            max_offset = self.info.total_addresses - 1

        last_offset = self.start_offset + count - 1
        if last_offset > max_offset:
            raise ConfigurationError(
                f"Cannot fit {count} hosts from offset {self.start_offset} "
                f"in {network}: last offset {last_offset} exceeds {max_offset}"
            )

        base = network.network_address
        gateway = self.gateway
        subnet = str(network)
        return [
            HostAddress(
                index=i + 1,
                address=str(base + self.start_offset + i),
                subnet=subnet,
                gateway=gateway,
            )
            for i in range(count)
        ]


class SubnetPlanner:
    """Plan how a parent subnet is divided and assigned to groups."""

    def __init__(self, parent_cidr: str) -> None:
        self.parent = SubnetInfo.from_cidr(parent_cidr)

    def split_into_count(self, count: int) -> list[SubnetInfo]:
        return split_by_count(self.parent.network, count)

    def split_with_prefix(self, prefix_length: int) -> list[SubnetInfo]:
        from .subnet import split_subnet
        return split_subnet(self.parent.network, prefix_length)

    def assign_to_groups(
        self,
        group_count: int,
        hosts_per_group: int,
        start_offset: int = 10,
        gateway_offset: int = 1,
    ) -> list[tuple[SubnetInfo, list[HostAddress]]]:
        """Split into `group_count` subnets and plan `hosts_per_group` each."""
        subnets = self.split_into_count(group_count)
        result: list[tuple[SubnetInfo, list[HostAddress]]] = []
        for subnet in subnets:
            planner = HostIPPlanner(
                cidr=str(subnet.network),
                start_offset=start_offset,
                gateway_offset=gateway_offset,
            )
            result.append((subnet, planner.plan(hosts_per_group)))
        return result