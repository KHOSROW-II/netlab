"""Platform abstraction for sysctl, admin check, and OS hints."""

from .base import AdminStatus, PlatformAdapter
from .detect import detect_platform

__all__ = ["PlatformAdapter", "AdminStatus", "detect_platform"]