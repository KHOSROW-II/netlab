"""Unit tests for terminal animation."""
import time

from netlab.animate import animate_events
from netlab.protocols.event import ProtocolEvent


class TestAnimate:
    def test_animation_completes_quickly(self, capsys):
        events = [
            ProtocolEvent(1, "L3", "ICMP", "10.0.0.1", "10.0.0.2",
                          "echo request"),
            ProtocolEvent(2, "L3", "ICMP", "10.0.0.2", "10.0.0.1",
                          "echo reply"),
        ]
        start = time.time()
        animate_events(events, delay_ms=1, color=False, title="Test")
        elapsed = time.time() - start
        assert elapsed < 1.0
        captured = capsys.readouterr()
        assert "ICMP" in captured.out
        assert "echo request" in captured.out

    def test_animation_handles_empty(self, capsys):
        animate_events([], delay_ms=1, color=False, title="Empty")
        out = capsys.readouterr().out
        assert "Empty" in out