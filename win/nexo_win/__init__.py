"""Nexo para Windows: interfaz web (pywebview + xterm.js) sobre el mismo núcleo de Nexo.

El núcleo (bóveda, conexiones, llaves, temas) vive en el paquete `nexo` de la raíz
del repositorio y no depende de GTK; este paquete solo agrega la interfaz.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IS_WINDOWS = sys.platform == "win32"


def setup_paths():
    """Rutas de datos antes de importar el núcleo.

    En Windows la bóveda y los ajustes van a %APPDATA%\\nexo (el núcleo usa las
    variables XDG, que Windows no define). En Linux no se toca nada: se comparte
    la bóveda de la app GTK, útil para probar.
    """
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        os.environ.setdefault("XDG_DATA_HOME", appdata)
        os.environ.setdefault("XDG_CONFIG_HOME", appdata)
    # Empaquetado con PyInstaller el núcleo viaja dentro; en desarrollo está en la raíz del repo.
    if not getattr(sys, "frozen", False) and REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
