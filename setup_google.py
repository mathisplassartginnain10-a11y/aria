"""
setup_google.py — Authentification Google initiale (une seule fois).

Lance : .venv\\Scripts\\python.exe setup_google.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from actions.google_auth import credentials_path, get_credentials, is_configured


def main() -> None:
    print("Authentification Google OAuth2 pour ARIA...")
    creds_file = credentials_path()
    if not creds_file:
        print()
        print("❌ credentials.json introuvable.")
        print(f"   Place le fichier OAuth Desktop ici : {ROOT / 'credentials.json'}")
        print("   (Console Google Cloud → Identifiants → Application de bureau)")
        sys.exit(1)

    print(f"Credentials : {creds_file}")
    print("Une fenêtre Chrome va s'ouvrir pour te connecter.")
    print()
    get_credentials(interactive=True)
    print()
    print("✅ Authentification réussie !")
    print("Token sauvegardé dans data/google_token.json")
    print()
    print("APIs disponibles : Docs, Drive, Calendar, Gmail, Sheets, Forms")
    if not is_configured():
        print("(Attention : credentials.json non détecté après auth — vérifie le chemin)")


if __name__ == "__main__":
    main()
