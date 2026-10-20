"""Linux platform adapter."""
import logging
import os
import subprocess

from .base import AdminStatus, PlatformAdapter

logger = logging.getLogger(__name__)

SYSCTL_PERSIST_FILE = "/etc/sysctl.d/99-netlab.conf"


class LinuxAdapter(PlatformAdapter):
    @property
    def name(self) -> str:
        return "linux"

    def admin_status(self) -> AdminStatus:
        try:
            is_root = os.geteuid() == 0
        except AttributeError:
            is_root = False
        can_elevate = self._sudo_available()
        hint = "root" if is_root else "Run with sudo to apply system changes."
        return AdminStatus(
            is_admin=is_root, can_elevate=can_elevate, hint=hint,
        )

    def _sudo_available(self) -> bool:
        try:
            r = subprocess.run(
                ["sudo", "-n", "true"],
                capture_output=True, timeout=2,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def read_sysctl(self, key: str) -> str | None:
        try:
            r = subprocess.run(
                ["sysctl", "-n", key],
                capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                return r.stdout.decode().strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def apply_sysctl(self, key: str, value: str) -> bool:
        try:
            r = subprocess.run(
                ["sysctl", "-w", f"{key}={value}"],
                capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                logger.info("sysctl %s=%s applied", key, value)
                return True
            logger.warning(
                "sysctl failed: %s",
                r.stderr.decode(errors="ignore").strip(),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("sysctl unusable: %s", exc)
        return False

    def persist_commands(self, key: str, value: str) -> list[str]:
        return [
            f"echo '{key} = {value}' | sudo tee -a {SYSCTL_PERSIST_FILE}",
            "sudo sysctl --system",
        ]

    def docker_hint(self) -> str:
        return "Docker runs natively on Linux."