"""Unit tests for the firewall manager."""
from netlab.firewall import FirewallManager, SYSCTL_KEY
from netlab.topology import GroupSpec, LabTopology, RouterSpec


def _topo(groups, routers=()):
    topo = LabTopology(
        groups=[
            GroupSpec(name=n, subnet=s, host_count=1)
            for n, s in groups
        ],
        routers=list(routers),
    )
    topo.validate()
    return topo


class TestHasRouters:
    def test_no_routers(self):
        fm = FirewallManager(_topo([("a", "10.10.0.0/24")]))
        assert fm.has_routers() is False

    def test_one_router(self):
        topo = _topo(
            [("a", "10.10.0.0/24"), ("b", "10.30.0.0/24")],
            routers=[RouterSpec(name="r1", connects=("a", "b"))],
        )
        fm = FirewallManager(topo)
        assert fm.has_routers() is True


class TestState:
    def test_no_routers_never_needs_change(self):
        fm = FirewallManager(_topo([("a", "10.10.0.0/24")]))
        state = fm.state()
        assert state.needs_change is False
        assert state.value in ("0", "1", "unknown")

    def test_with_routers_reports_fields(self):
        topo = _topo(
            [("a", "10.10.0.0/24"), ("b", "10.30.0.0/24")],
            routers=[RouterSpec(name="r1", connects=("a", "b"))],
        )
        fm = FirewallManager(topo)
        state = fm.state()
        assert isinstance(state.needs_change, bool)
        assert isinstance(state.can_change, bool)
        assert isinstance(state.hint, str)
        # When a change is needed, the hint must give a concrete command.
        if state.needs_change:
            assert "sudo" in state.hint.lower() or "wsl" in state.hint.lower()


class TestPersistCommands:
    def test_no_routers_empty(self):
        fm = FirewallManager(_topo([("a", "10.10.0.0/24")]))
        assert fm.persist_commands() == []

    def test_with_routers_produces_commands(self):
        topo = _topo(
            [("a", "10.10.0.0/24"), ("b", "10.30.0.0/24")],
            routers=[RouterSpec(name="r1", connects=("a", "b"))],
        )
        cmds = FirewallManager(topo).persist_commands()
        assert len(cmds) >= 2
        assert any("99-netlab.conf" in c for c in cmds)
        assert any(SYSCTL_KEY in c for c in cmds)