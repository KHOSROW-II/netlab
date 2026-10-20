"""First-run environment checks for the desktop build."""
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

DOCKER_DOWNLOAD_URL = (
    "https://desktop.docker.com/win/main/amd64/"
    "Docker%20Desktop%20Installer.exe"
)


class SetupNeeded(Exception):
    pass


def show_message(title: str, text: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
            return
        except Exception:
            pass
    print(f"{title}: {text}")


def ask_yes_no(title: str, text: str) -> bool:
    if sys.platform == "win32":
        try:
            import ctypes
            result = ctypes.windll.user32.MessageBoxW(0, text, title, 0x24)
            return result == 6
        except Exception:
            pass
    answer = input(f"{title}: {text} [y/N] ").strip().lower()
    return answer in ("y", "yes")


def download_docker_installer() -> Path | None:
    if sys.platform != "win32":
        return None
    dest = Path.home() / "Downloads" / "DockerDesktopInstaller.exe"
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Docker Desktop to {dest} ...")
    try:
        urllib.request.urlretrieve(DOCKER_DOWNLOAD_URL, dest)
        print("Download complete.")
        return dest
    except Exception as exc:
        print(f"Download failed: {exc}")
        return None


def launch_installer(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen([str(path)], shell=True)
    else:
        subprocess.Popen(["xdg-open", str(path)])


def check_docker() -> None:
    if not shutil.which("docker"):
        raise SetupNeeded("DOCKER_NOT_INSTALLED")
    try:
        r = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, timeout=10,
        )
        if r.returncode != 0:
            raise SetupNeeded("DOCKER_NOT_RUNNING")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        raise SetupNeeded("DOCKER_NOT_RUNNING")


def run_setup() -> bool:
    try:
        check_docker()
        return True
    except SetupNeeded:
        pass

    text = (
        "NetLab requires Docker Desktop.\n\n"
        "Docker Desktop was not detected on this machine.\n\n"
        "Download and install it now?"
    )
    if not ask_yes_no("NetLab - Docker required", text):
        return False

    installer = download_docker_installer()
    if installer is None:
        show_message(
            "Download failed",
            f"Please download Docker Desktop manually:\n{DOCKER_DOWNLOAD_URL}",
        )
        return False

    show_message(
        "Installation starting",
        "Docker Desktop installer will open.\n"
        "Follow its prompts, then launch NetLab again.",
    )
    launch_installer(installer)
    return False
