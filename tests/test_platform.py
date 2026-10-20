"""Tests for the platform abstraction layer."""
import sys
from unittest.mock import patch

from netlab.platform.base import AdminStatus
from netlab.platform.linux import LinuxAdapter
from netlab.platform.windows import WindowsNativeAdapter, WindowsWSL2Adapter


class TestLinuxAdapter:
    def test_name(self):
        assert LinuxAdapter().name == "linux"

    def test_read_sysctl_shape(self):
        v = LinuxAdapter().read_sysctl("net.bridge.bridge-nf-call-iptables")
        assert v is None or isinstance(v, str)

    def test_persist_commands(self):
        cmds = LinuxAdapter().persist_commands("x.y", "0")
        assert any("sudo" in c for c in cmds)
        assert any("99-netlab.conf" in c for c in cmds)

    def test_admin_status_shape(self):
        s = LinuxAdapter().admin_status()
        assert isinstance(s, AdminStatus)
        assert isinstance(s.is_admin, bool)
        assert isinstance(s.can_elevate, bool)
        assert isinstance(s.hint, str)


class TestWindowsWSL2Adapter:
    def test_name_includes_distro(self):
        assert "Debian" in WindowsWSL2Adapter("Debian").name

    def test_persist_commands_use_wsl(self):
        cmds = WindowsWSL2Adapter().persist_commands("x", "0")
        assert cmds
        assert all("wsl" in c.lower() for c in cmds)


class TestWindowsNativeAdapter:
    def test_no_sysctl(self):
        a = WindowsNativeAdapter()
        assert a.apply_sysctl("x", "0") is False
        assert a.read_sysctl("x") is None
        assert a.persist_commands("x", "0") == []

    def test_admin_hint_mentions_wsl(self):
        assert "WSL2" in WindowsNativeAdapter().admin_status().hint


class TestDetection:
    def test_linux(self):
        with patch.object(sys, "platform", "linux"):
            from netlab.platform.detect import detect_platform
            assert detect_platform().name == "linux"

    def test_windows_with_wsl(self):
        with patch.object(sys, "platform", "win32"), \
             patch("shutil.which", return_value="/usr/bin/wsl"):
            from netlab.platform.detect import detect_platform
            assert detect_platform().name.startswith("windows-wsl2")

    def test_windows_without_wsl(self):
        with patch.object(sys, "platform", "win32"), \
             patch("shutil.which", return_value=None):
            from netlab.platform.detect import detect_platform
            assert detect_platform().name == "windows-native"