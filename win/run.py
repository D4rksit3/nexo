"""Punto de entrada: python win/run.py (en desarrollo) o el .exe empaquetado."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nexo_win.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
