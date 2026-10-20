"""Windows adapter (WSL2 backend for sysctl, plus native fallback)."""
import logging
import shutil
import subprocess

from .base import AdminStatus, PlatformAdapter

logger = logging.getLogger(__name__)

DEFAULT_WSL_DISTRO = "Ubuntu"


class WindowsWSL2Adapter(PlatformAdapter):
    """Runs sysctl inside WSL2 (Docker Desktop's backend)."""

    def __init__(self, distro: str = DEFAULT_WSL_DISTRO) -> None:
        self._distro = distro

    @property
    def name(self) -> str:
        return f"windows-wsl2({self._distro})"

    def _wsl(self, *args: str, timeout: int = 10) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["wsl", "-d", self._distro, "--", *args],
            capture_output=True, timeout=timeout,
        )

    def admin_status(self) -> AdminStatus:
        try:
            r = self._wsl("sudo", "-n", "true")
            can_elevate = r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            can_elevate = False
        hint = (
            f"Run inside WSL2 ({self._distro}) with sudo, or run the "
            f"printed commands."
        )
        return AdminStatus(
            is_admin=False, can_elevate=can_elevate, hint=hint,
        )

    def read_sysctl(self, key: str) -> str | None:
        try:
            r = self._wsl("sysctl", "-n", key)
            if r.returncode == 0:
                return r.stdout.decode().strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def apply_sysctl(self, key: str, value: str) -> bool:
        try:
            r = self._wsl("sudo", "-n", "sysctl", "-w", f"{key}={value}")
            if r.returncode == 0:
                logger.info("sysctl %s=%s applied via WSL2", key, value)
                return True
            logger.warning(
                "WSL2 sysctl failed: %s",
                r.stderr.decode(errors="ignore").strip(),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("WSL2 unusable: %s", exc)
        return False

    def persist_commands(self, key: str, value: str) -> list[str]:
        return [
            f"wsl -d {self._distro} -e sudo sh -c "
            f"\"echo '{key} = {value}' > /etc/sysctl.d/99-netlab.conf\"",
            f"wsl -d {self._distro} -e sudo sysctl --system",
        ]

    def docker_hint(self) -> str:
        return (
            f"Docker Desktop with WSL2 backend ({self._distro}). "
            "If Docker is unreachable, open Docker Desktop."
        )


class WindowsNativeAdapter(PlatformAdapter):
    """Fallback when WSL2 is not available (sysctl unavailable)."""

    @property
    def name(self) -> str:
        return "windows-native"

    def admin_status(self) -> AdminStatus:
        return AdminStatus(
            is_admin=False, can_elevate=False,
            hint="WSL2 not detected. Install Docker Desktop with WSL2 backend.",
        )

    def read_sysctl(self, key: str) -> str | None:
        return None

    def apply_sysctl(self, key: str, value: str) -> bool:
        return False

    def persist_commands(self, key: str, value: str) -> list[str]:
        return []

    def docker_hint(self) -> str:
        return "Install Docker Desktop with WSL2 backend, then re-run."