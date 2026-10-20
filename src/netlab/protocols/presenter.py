"""Text presenters for protocol events."""
from .event import ProtocolEvent


def render_timeline(events: list[ProtocolEvent], title: str = "") -> str:
    """Render a chronological, aligned timeline of protocol events."""
    if not events:
        return title + "\n(no events)" if title else "(no events)"

    lines: list[str] = []
    if title:
        lines.append(title)
        lines.append("=" * 96)
    lines.append(
        f"{'#':>3}  {'LAYER':<4} {'PROTO':<5} "
        f"{'SOURCE':<17} {'DESTINATION':<17} INFO"
    )
    lines.append("-" * 96)
    for e in events:
        lines.append(
            f"{e.step:>3}  {e.layer:<4} {e.protocol:<5} "
            f"{e.src:<17} {e.dst:<17} {e.info}"
        )
    return "\n".join(lines)


def render_summary(events: list[ProtocolEvent]) -> str:
    """Short summary: counts by protocol and layer."""
    from collections import Counter

    if not events:
        return "(no events)"

    by_proto = Counter(e.protocol for e in events)
    by_layer = Counter(e.layer for e in events)

    lines = [f"Total events : {len(events)}"]
    lines.append("By protocol  : " + ", ".join(
        f"{k}={v}" for k, v in sorted(by_proto.items())
    ))
    lines.append("By layer     : " + ", ".join(
        f"{k}={v}" for k, v in sorted(by_layer.items())
    ))
    return "\n".join(lines)
