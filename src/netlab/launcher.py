"""Entry point for the PyInstaller bundle."""
import os
import sys

if getattr(sys, "frozen", False):
    # PyInstaller puts bundled files in sys._MEIPASS
    sys.path.insert(0, sys._MEIPASS)

from netlab.desktop import main

if __name__ == "__main__":
    sys.exit(main())