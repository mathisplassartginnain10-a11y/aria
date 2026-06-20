"""
agents.py — Gestion des agents IA personnalisables dans ARIA.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

import app_paths

logger = logging.getLogger(__name__)

_active_agent_id: str = "default"

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _default_agent() -> dict:
    return {
        "id": "default",
        "name": "ARIA",
        "icon": "🤖",
        "color": "#6C8EFF",
        "model": "llama3.1:8b-instruct-q8_0",
        "system_prompt": "",
        "rules": [],
        "git_repos": [],
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }


def _load_agents() -> dict:
    """Charge tous les agents depuis config.yaml."""
    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        agents = cfg.get("agents", {})
        if "default" not in agents:
            agents["default"] = _default_agent()
        return agents
    except Exception as exc:
        logger.error("Erreur chargement agents: %s", exc)
        return {"default": _default_agent()}


def _save_agents(agents: dict) -> None:
    """Sauvegarde les agents dans config.yaml (écriture atomique)."""
    cfg_path = app_paths.config_path()
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        cfg["agents"] = agents
        text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
        fd, tmp = tempfile.mkstemp(dir=str(cfg_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, cfg_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as exc:
        logger.error("Erreur sauvegarde agents: %s", exc)
        raise


def get_all_agents() -> list[dict]:
    """Retourne la liste de tous les agents."""
    return list(_load_agents().values())


def get_agent(agent_id: str) -> dict | None:
    """Retourne un agent par son ID."""
    return _load_agents().get(agent_id)


def create_agent(
    name: str,
    icon: str = "🤖",
    color: str = "#6C8EFF",
    model: str | None = None,
    system_prompt: str = "",
    rules: list[str] | None = None,
    git_repos: list[str] | None = None,
) -> dict:
    """Crée un nouvel agent."""
    from llm import MODELS

    agents = _load_agents()

    base_id = name.lower().replace(" ", "_")[:20]
    agent_id = base_id
    counter = 1
    while agent_id in agents:
        agent_id = f"{base_id}_{counter}"
        counter += 1

    agent = {
        "id": agent_id,
        "name": name,
        "icon": icon,
        "color": color,
        "model": model or MODELS.get("fast", "llama3.1:8b-instruct-q8_0"),
        "system_prompt": system_prompt,
        "rules": rules or [],
        "git_repos": git_repos or [],
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }

    agents[agent_id] = agent
    _save_agents(agents)
    logger.info("Agent créé: %s (%s)", name, agent_id)
    return agent


def update_agent(agent_id: str, **kwargs) -> dict:
    """Met à jour un agent existant."""
    agents = _load_agents()
    if agent_id not in agents:
        raise ValueError(f"Agent '{agent_id}' inexistant")

    if agent_id == "default" and "id" in kwargs:
        del kwargs["id"]

    agents[agent_id].update(kwargs)
    _save_agents(agents)
    logger.info("Agent mis à jour: %s", agent_id)
    return agents[agent_id]


def delete_agent(agent_id: str) -> bool:
    """Supprime un agent (sauf default)."""
    if agent_id == "default":
        raise ValueError("L'agent par défaut ne peut pas être supprimé")

    agents = _load_agents()
    if agent_id not in agents:
        return False

    del agents[agent_id]
    _save_agents(agents)

    global _active_agent_id
    if _active_agent_id == agent_id:
        _active_agent_id = "default"

    logger.info("Agent supprimé: %s", agent_id)
    return True


def get_active_agent() -> dict:
    """Retourne l'agent actif."""
    agent = get_agent(_active_agent_id)
    return agent or _default_agent()


def set_active_agent(agent_id: str) -> dict:
    """Change l'agent actif."""
    global _active_agent_id
    agent = get_agent(agent_id)
    if not agent:
        raise ValueError(f"Agent '{agent_id}' inexistant")
    _active_agent_id = agent_id
    logger.info("Agent actif: %s (%s)", agent["name"], agent_id)
    return agent


def get_git_context(agent: dict, max_files: int = 10) -> str:
    """
    Génère un résumé du contexte Git pour un agent.
    Liste les fichiers récemment modifiés dans chaque repo.
    """
    if not agent.get("git_repos"):
        return ""

    context_parts: list[str] = []

    for repo_path in agent["git_repos"]:
        repo = Path(repo_path)
        if not repo.exists() or not (repo / ".git").exists():
            logger.debug("Repo non trouvé ou pas un repo Git: %s", repo_path)
            continue

        try:
            result = subprocess.run(
                ["git", "log", "--name-only", "--pretty=format:", "--since=1 week ago"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_SUBPROCESS_FLAGS,
            )
            files = [f.strip() for f in result.stdout.split("\n") if f.strip()]
            unique_files = list(dict.fromkeys(files))[:max_files]

            last_commit = subprocess.run(
                ["git", "log", "-1", "--pretty=format:%h %s (%ar)"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_SUBPROCESS_FLAGS,
            )

            repo_name = repo.name
            context_parts.append(
                f"Repo '{repo_name}' ({repo_path}):\n"
                f"  Dernier commit: {last_commit.stdout.strip()}\n"
                f"  Fichiers récents: {', '.join(unique_files[:5]) if unique_files else 'aucun'}"
            )
        except Exception as exc:
            logger.debug("Erreur git context %s: %s", repo_path, exc)

    return "\n\n".join(context_parts)


def build_system_prompt(agent: dict, base_prompt: str = "") -> str:
    """
    Construit le system prompt complet pour un agent.
    Combine : base ARIA + custom agent + règles + contexte Git.
    """
    parts: list[str] = []

    if base_prompt:
        parts.append(base_prompt)

    if agent.get("system_prompt"):
        parts.append(agent["system_prompt"])

    if agent.get("rules"):
        rules_text = "Règles à suivre impérativement :\n" + "\n".join(
            f"- {r}" for r in agent["rules"]
        )
        parts.append(rules_text)

    git_ctx = get_git_context(agent)
    if git_ctx:
        parts.append(f"Contexte des projets en cours :\n{git_ctx}")

    if agent.get("name") and agent["name"] != "ARIA":
        parts.append(f"Tu t'appelles {agent['name']}. Sois cohérent avec ce nom.")

    return "\n\n".join(p for p in parts if p)
