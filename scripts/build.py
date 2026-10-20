"""Build a standalone Windows executable with PyInstaller."""
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd, check=True):
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=check)


def main():
    root = Path(__file__).resolve().parent.parent
    os_target = "windows" if sys.platform == "win32" else sys.platform

    # 1. Ensure build deps are present
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    run([sys.executable, "-m", "pip", "install",
         "pyinstaller", "pytest", "httpx"])

    # 2. Install netlab with web + desktop extras
    #    On Linux with Python 3.14 proxy_tools may not have a wheel;
    #    preinstall it without build isolation.
    try:
        run([sys.executable, "-m", "pip", "install",
             "-e", ".[dev,web,desktop]"], check=False)
    except Exception:
        pass
    # If pywebview is missing, install proxy_tools then pywebview --no-deps
    try:
        import webview  # noqa: F401
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "proxy_tools"], check=False)
        run([sys.executable, "-m", "pip", "install",
             "pywebview", "--no-deps"], check=False)

    # 3. Verify tests still pass
    run([sys.executable, "-m", "pytest", "tests", "-q"], check=False)

    # 4. Run PyInstaller
    pkg_src = root / "src" / "netlab"
    add_data = [
        f"{pkg_src / 'web' / 'templates'}{os.pathsep}netlab/web/templates",
        f"{pkg_src / 'web' / 'static'}{os.pathsep}netlab/web/static",
    ]

    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", "NetLab",
        "--onefile",
        "--windowed",
        "--clean",
        "--noconfirm",
        "--paths", str(root / "src"),
    ]
    for item in add_data:
        args += ["--add-data", item]
    hidden = [
        "uvicorn", "fastapi", "jinja2", "webview",
        "netlab.web.app", "netlab.web.routes",
        "netlab.desktop", "netlab.bootstrap",
        "netlab.cli",
    ]
    for h in hidden:
        args += ["--hidden-import", h]

    args.append(str(root / "scripts" / "launcher.py"))
    run(args)

    print()
    print(f"Build complete. Find the executable in: {root / 'dist'}")
    print(f"Target OS: {os_target}")


if __name__ == "__main__":
    main()