"""Abstract base for platform-specific operations."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AdminStatus:
    """Whether the current process can change system settings."""

    is_admin: bool
    can_elevate: bool
    hint: str


class PlatformAdapter(ABC):
    """OS-specific operations that NetLab needs."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short OS identifier, e.g. 'linux', 'windows-wsl2(Ubuntu)'."""

    @abstractmethod
    def admin_status(self) -> AdminStatus:
        """Is the process privileged, and can it elevate?"""

    @abstractmethod
    def read_sysctl(self, key: str) -> str | None:
        """Read a sysctl value or return None if unavailable."""

    @abstractmethod
    def apply_sysctl(self, key: str, value: str) -> bool:
        """Set a sysctl value. Returns success."""

    @abstractmethod
    def persist_commands(self, key: str, value: str) -> list[str]:
        """Commands the operator can run to make the change durable."""

    @abstractmethod
    def docker_hint(self) -> str:
        """Human-readable guidance on how Docker works on this OS."""