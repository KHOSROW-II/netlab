"""Platform detection."""
import shutil
import sys

from .base import PlatformAdapter


def detect_platform() -> PlatformAdapter:
    """Return the appropriate adapter for the current OS."""
    if sys.platform.startswith("linux"):
        from .linux import LinuxAdapter
        return LinuxAdapter()
    if sys.platform == "win32":
        from .windows import WindowsNativeAdapter, WindowsWSL2Adapter
        if shutil.which("wsl"):
            return WindowsWSL2Adapter()
        return WindowsNativeAdapter()
    if sys.platform == "darwin":
        # macOS uses sysctl but has no geteuid-as-root semantics for Docker
        from .linux import LinuxAdapter
        return LinuxAdapter()
    from .linux import LinuxAdapter
    return LinuxAdapter()