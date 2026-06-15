"""Script one-shot OAuth Google (Drive + Calendar + Docs)."""

from actions.google_auth import run_oauth_flow

if __name__ == "__main__":
    print("Authentification Google pour ARIA...")
    print("Une fenêtre de navigateur va s'ouvrir.")
    run_oauth_flow()
    print("Configuration terminée. Redémarre ARIA.")
