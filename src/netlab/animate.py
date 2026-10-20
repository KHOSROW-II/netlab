"""Terminal animation of protocol events."""
import sys
import time

from .protocols.event import ProtocolEvent

_COLORS = {
    "ARP": "\033[33m",     # yellow
    "ICMP": "\033[36m",    # cyan
    "DNS": "\033[35m",     # magenta
    "DHCP": "\033[32m",    # green
}
_RESET = "\033[0m"
_DIM = "\033[2m"


def animate_events(
    events: list[ProtocolEvent],
    delay_ms: int = 400,
    color: bool = True,
    title: str = "",
) -> None:
    """Print each event with delay, prefix, and ANSI color."""
    if title:
        print(title)
        print("=" * 96)
    for event in events:
        prefix_color = _COLORS.get(event.protocol, "") if color else ""
        reset = _RESET if color else ""
        dim = _DIM if color else ""

        print(
            f"{prefix_color}[{event.step:03d}] {event.layer} {event.protocol}"
            f"{reset} {event.src} {dim}->{reset} {event.dst}"
        )
        print(f"      {event.info}")
        if event.at_node:
            print(f"      {dim}@ {event.at_node}{reset}")
        sys.stdout.flush()
        time.sleep(delay_ms / 1000.0)
    if title:
        print("=" * 96)