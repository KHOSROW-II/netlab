"""Base class for pure-Python protocol simulations."""
from abc import ABC, abstractmethod

from ..ipam import HostIPPlanner
from ..topology import GroupSpec, LabTopology
from .event import ProtocolEvent


class Simulator(ABC):
    """Shared plumbing for protocol simulators (no Docker required)."""

    def __init__(
        self,
        topo: LabTopology,
        group_name: str,
        src_idx: int = 1,
        dst_idx: int = 2,
    ) -> None:
        self.topo = topo
        self.group_name = group_name
        self.src_idx = src_idx
        self.dst_idx = dst_idx
        self._events: list[ProtocolEvent] = []
        self._step = 0

    @property
    def spec(self) -> GroupSpec:
        return self.topo.group(self.group_name)

    def _planner(self) -> HostIPPlanner:
        return HostIPPlanner(
            cidr=self.spec.subnet,
            start_offset=self.spec.start_offset,
            gateway_offset=self.spec.gateway_offset,
        )

    def _ip(self, idx: int) -> str:
        return self._planner().plan(idx)[-1].address

    def _emit(
        self,
        layer: str,
        protocol: str,
        src: str,
        dst: str,
        info: str,
        at_node: str = "",
    ) -> None:
        self._step += 1
        self._events.append(ProtocolEvent(
            step=self._step,
            layer=layer,
            protocol=protocol,
            src=src,
            dst=dst,
            info=info,
            at_node=at_node,
        ))

    @abstractmethod
    def run(self) -> list[ProtocolEvent]:
        """Execute the simulation and return the event list."""
