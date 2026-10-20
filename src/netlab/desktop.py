"""Desktop entry point used by the PyInstaller build."""
import sys


def main() -> int:
    from .bootstrap import run_setup, show_message

    if not run_setup():
        return 0

    from .cli import main as cli_main
    try:
        return cli_main(["web"])
    except Exception as exc:
        show_message("NetLab error", f"Unexpected error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
