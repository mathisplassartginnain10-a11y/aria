import logging
import subprocess
import sys
from pathlib import Path

import memory
import app_paths

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_last_repo: Path | None = None


def _run(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    cwd = cwd or _last_repo or Path.cwd()
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip() or result.stderr.strip()
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 1, "Commande git expirée."
    except FileNotFoundError:
        return 1, "Git n'est pas installé."


def _find_repo() -> Path | None:
    global _last_repo
    if _last_repo and (_last_repo / ".git").exists():
        return _last_repo
    stored = memory.recall("context.last_git_repo")
    if stored and Path(stored).exists():
        _last_repo = Path(stored)
        return _last_repo
    cwd = Path.cwd()
    if (cwd / ".git").exists():
        _last_repo = cwd
        return cwd
    return None


def status() -> str:
    repo = _find_repo()
    if not repo:
        return "Aucun dépôt Git trouvé."
    code, output = _run(["git", "status", "--short"], repo)
    if code != 0:
        return output
    if not output:
        return "Rien à committer, arbre de travail propre."
    lines = output.split("\n")
    return f"Statut git : {len(lines)} fichier(s) modifié(s). {output[:200]}"


def add_all() -> str:
    repo = _find_repo()
    if not repo:
        return "Aucun dépôt Git trouvé."
    code, output = _run(["git", "add", "."], repo)
    return "Tous les fichiers ajoutés." if code == 0 else output


def commit(message: str) -> str:
    repo = _find_repo()
    if not repo:
        return "Aucun dépôt Git trouvé."
    code, output = _run(["git", "commit", "-m", message], repo)
    return f"Commit créé : {message}" if code == 0 else output


def push() -> str:
    repo = _find_repo()
    if not repo:
        return "Aucun dépôt Git trouvé."
    code, output = _run(["git", "push"], repo)
    return "Code poussé sur le remote." if code == 0 else output


def pull() -> str:
    repo = _find_repo()
    if not repo:
        return "Aucun dépôt Git trouvé."
    code, output = _run(["git", "pull"], repo)
    return "Code mis à jour depuis le remote." if code == 0 else output


def create_branch(name: str) -> str:
    repo = _find_repo()
    if not repo:
        return "Aucun dépôt Git trouvé."
    code, output = _run(["git", "checkout", "-b", name], repo)
    return f"Branche {name} créée." if code == 0 else output


def switch_branch(name: str) -> str:
    repo = _find_repo()
    if not repo:
        return "Aucun dépôt Git trouvé."
    code, output = _run(["git", "checkout", name], repo)
    return f"Basculement sur la branche {name}." if code == 0 else output


def log(n: int = 5) -> str:
    repo = _find_repo()
    if not repo:
        return "Aucun dépôt Git trouvé."
    code, output = _run(["git", "log", f"-{n}", "--oneline"], repo)
    return output if code == 0 else "Impossible de lire l'historique git."