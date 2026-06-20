"""
Point d'entrée legacy — redirige vers le backend Electron (python/main.py).

Pour lancer ARIA :
  Terminal 1 : cd python && ..\\.venv\\Scripts\\python.exe main.py
  Terminal 2 : cd electron && npm start
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "python" / "main.py"
    if not target.exists():
        print("Erreur: python/main.py introuvable. Migration Electron requise.")
        sys.exit(1)
    runpy.run_path(str(target), run_name="__main__")
