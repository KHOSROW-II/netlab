"""Build a standalone Windows executable with PyInstaller."""
import os
import subprocess
import sys
from pathlib import Path


def run(cmd, check=True):
    print("$", " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd, check=check)
    return result.returncode


def main():
    root = Path(__file__).resolve().parent.parent

    # 1. Verify dependencies are installed
    try:
        import webview  # noqa: F401
        import fastapi  # noqa: F401
        import docker  # noqa: F401
    except ImportError as exc:
        print(f"Missing dependency: {exc}", file=sys.stderr)
        print("Run setup.ps1 first.", file=sys.stderr)
        return 1

    # 2. Run tests as a gate — never build if they fail
    print("Running tests before build...")
    rc = run([sys.executable, "-m", "pytest", "tests", "-q"], check=False)
    if rc != 0:
        print("Tests failed. Aborting build.", file=sys.stderr)
        return rc

    # 3. PyInstaller args
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
        "uvicorn", "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan", "uvicorn.lifespan.on",
        "fastapi", "jinja2", "webview", "bottle",
        "netlab.web.app", "netlab.web.routes",
        "netlab.desktop", "netlab.bootstrap",
        "netlab.cli",
    ]
    for h in hidden:
        args += ["--hidden-import", h]

    args.append(str(root / "scripts" / "launcher.py"))

    # 4. Build
    rc = run(args, check=False)
    if rc != 0:
        print("Build failed.", file=sys.stderr)
        return rc

    exe_path = root / "dist" / "NetLab.exe"
    print()
    print("=" * 60)
    print(f"Build complete: {exe_path}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())