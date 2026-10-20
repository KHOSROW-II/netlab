"""Tests for auto-remediation and watch mode."""
from unittest.mock import MagicMock

from netlab.fixer import FixAction, Fixer, FixReport
from netlab.topology import GroupSpec, LabTopology, RouterSpec
from netlab.watcher import ClusterWatcher


def _topo():
    return LabTopology(
        groups=[GroupSpec(name="g", subnet="10.0.0.0/24", host_count=2)],
    )


class TestFixReport:
    def test_empty_ok(self):
        assert FixReport().all_ok is True

    def test_with_failure(self):
        r = FixReport(actions=[
            FixAction("a", True, ""),
            FixAction("b", False, "x"),
        ])
        assert r.all_ok is False

    def test_print(self, capsys):
        FixReport(actions=[FixAction("a", True, "done")]).print()
        out = capsys.readouterr().out
        assert "[ OK ]" in out


class TestFixerBrNetfilter:
    def test_already_disabled(self):
        adapter = MagicMock()
        adapter.read_sysctl.return_value = "0"
        fixer = Fixer(None, client=MagicMock(), adapter=adapter)
        report = fixer.run()
        assert report.all_ok
        assert len(report.actions) == 1
        assert report.actions[0].label == "br_netfilter"
        adapter.apply_sysctl.assert_not_called()

    def test_enabled_and_fixable(self):
        adapter = MagicMock()
        adapter.read_sysctl.return_value = "1"
        admin = MagicMock()
        admin.is_admin = True
        admin.can_elevate = True
        adapter.admin_status.return_value = admin
        adapter.apply_sysctl.return_value = True
        fixer = Fixer(None, client=MagicMock(), adapter=adapter)
        report = fixer.run()
        assert report.all_ok
        assert adapter.apply_sysctl.call_count == 2

    def test_enabled_not_privileged(self):
        adapter = MagicMock()
        adapter.read_sysctl.return_value = "1"
        admin = MagicMock()
        admin.is_admin = False
        admin.can_elevate = False
        admin.hint = "run as root"
        adapter.admin_status.return_value = admin
        adapter.persist_commands.return_value = ["sudo sysctl -w x=0"]
        fixer = Fixer(None, client=MagicMock(), adapter=adapter)
        report = fixer.run()
        assert not report.all_ok
        assert "not privileged" in report.actions[0].detail


class TestFixerOrphans:
    def test_orphan_container_removed(self):
        topo = _topo()
        client = MagicMock()
        orphan = MagicMock()
        orphan.name = "netlab-oldhost"
        orphan.status = "exited"
        client.containers.list.return_value = [orphan]
        client.networks.list.return_value = []
        adapter = MagicMock()
        adapter.read_sysctl.return_value = "0"
        fixer = Fixer(topo, client=client, adapter=adapter)
        report = fixer.run()
        assert any("orphan" in a.label and a.success for a in report.actions)
        orphan.remove.assert_called_once_with(force=True)

    def test_expected_container_restarted(self):
        topo = _topo()
        client = MagicMock()
        c = MagicMock()
        c.name = "netlab-g-host1"
        c.status = "exited"
        client.containers.list.return_value = [c]
        client.networks.list.return_value = []
        adapter = MagicMock()
        adapter.read_sysctl.return_value = "0"
        fixer = Fixer(topo, client=client, adapter=adapter)
        fixer.run()
        c.start.assert_called_once()


class TestWatcher:
    def test_healthy_cluster_no_actions(self):
        client = MagicMock()
        c = MagicMock()
        c.status = "running"
        client.containers.get.return_value = c
        w = ClusterWatcher(_topo(), client=client)
        assert w._tick() == []

    def test_dead_container_restarted(self):
        client = MagicMock()
        c = MagicMock()
        c.status = "exited"
        client.containers.get.return_value = c
        w = ClusterWatcher(_topo(), client=client, max_restarts=3)
        actions = w._tick()
        assert len(actions) == 2  # two hosts in _topo()
        c.start.assert_called()

    def test_max_restarts_reached(self):
        client = MagicMock()
        c = MagicMock()
        c.status = "exited"
        client.containers.get.return_value = c
        w = ClusterWatcher(_topo(), client=client, max_restarts=1)
        w._restarts["netlab-g-host1"] = 1
        actions = w._tick()
        assert any("gave up" in a for a in actions)