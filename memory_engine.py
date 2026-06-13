"""Moteur de mémoire persistante v12 — apprend de chaque session."""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import app_paths

logger = logging.getLogger(__name__)

SESSIONS_PATH = app_paths.data_dir() / "sessions.json"
PROFILE_PATH = app_paths.data_dir() / "user_profile.json"
PATTERNS_PATH = app_paths.data_dir() / "learned_patterns.json"
CONVERSATIONS_PATH = app_paths.data_dir() / "conversations.json"
FINE_TUNE_PATH = app_paths.data_dir() / "fine_tune_data.json"
CORRECTIONS_PATH = app_paths.data_dir() / "corrections.json"
PREFERENCES_PATH = app_paths.data_dir() / "preferences.json"
KNOWLEDGE_BASE_PATH = app_paths.data_dir() / "knowledge_base.json"

DEFAULT_PROFILE: dict = {
    "name": "mathi",
    "age_group": "lycéen",
    "location": "Couëron, France",
    "total_sessions": 0,
    "total_messages": 0,
    "total_tokens_generated": 0,
    "first_use": None,
    "last_use": None,
    "average_session_length": 0,
    "frequent_apps": {},
    "app_time_of_day": {},
    "last_apps_opened": [],
    "frequent_topics": {},
    "topic_depth": {},
    "interests_detected": [],
    "frequent_commands": {},
    "preferred_response_length": "normal",
    "preferred_language_style": "casual",
    "uses_voice": True,
    "uses_text": True,
    "voice_vs_text_ratio": 0.5,
    "positive_feedback_count": 0,
    "negative_feedback_count": 0,
    "correction_count": 0,
    "satisfaction_score": 0.0,
    "active_hours": {},
    "active_days": {},
    "peak_hour": None,
    "prefers_detailed_answers": False,
    "prefers_examples": True,
    "prefers_humor": False,
    "prefers_technical": False,
    "custom_vocabulary": {},
    "custom_shortcuts": {},
    "aviation": {
        "aircraft": "Robin DR400",
        "home_base": "LFRS",
        "license": "PPL en cours",
        "total_metar_requests": 0,
        "frequent_destinations": {},
    },
    "school": {
        "level": "Première",
        "specialties": ["Maths", "Allemand"],
        "bac_date": "2026",
        "frequent_subjects": {},
    },
    "gaming": {
        "favorite_games": {},
        "session_count": {},
    },
    "preferences": {},
}

DEFAULT_PATTERNS: dict = {
    "voice_shortcuts": {},
    "intent_corrections": {},
    "optimal_response_style": {
        "max_sentences": 6,
        "use_examples": True,
        "use_humor": False,
        "technical_level": "intermediate",
        "avoid_bullet_points_in_voice": True,
    },
    "command_sequences": [],
    "topic_app_associations": {},
    "schedule_patterns": {
        "morning_routine": [],
        "evening_routine": [],
    },
    "quality_exchanges": [],
}


def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Erreur lecture %s", path)
    return copy.deepcopy(default) if isinstance(default, (dict, list)) else default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_defaults(default: dict, existing: dict) -> dict:
    result = copy.deepcopy(default)
    if not isinstance(existing, dict):
        return result
    for key, val in existing.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _merge_defaults(result[key], val)
        else:
            result[key] = val
    return result


def _migrate_profile(profile: dict) -> dict:
    merged = _merge_defaults(DEFAULT_PROFILE, profile)
    if "corrections" in profile and isinstance(profile["corrections"], list):
        merged["correction_count"] = max(
            merged.get("correction_count", 0),
            len(profile["corrections"]),
        )
    if profile.get("preferences", {}).get("positive_feedback"):
        merged["positive_feedback_count"] = max(
            merged.get("positive_feedback_count", 0),
            profile["preferences"]["positive_feedback"],
        )
    if not merged.get("total_sessions") and profile.get("total_sessions"):
        merged["total_sessions"] = profile["total_sessions"]
    if not merged.get("total_messages") and profile.get("total_messages"):
        merged["total_messages"] = profile["total_messages"]
    return merged


def _migrate_patterns(patterns: dict) -> dict:
    merged = _merge_defaults(DEFAULT_PATTERNS, patterns)
    if patterns.get("app_shortcuts") and not merged.get("voice_shortcuts"):
        merged["voice_shortcuts"] = dict(patterns["app_shortcuts"])
    return merged


class MemoryEngine:
    def __init__(self) -> None:
        self.sessions: list = load_json(SESSIONS_PATH, [])
        raw_profile = load_json(PROFILE_PATH, {})
        self.profile: dict = _migrate_profile(raw_profile if raw_profile else {})
        raw_patterns = load_json(PATTERNS_PATH, {})
        self.patterns: dict = _migrate_patterns(raw_patterns if raw_patterns else {})
        self.conversations: list = load_json(CONVERSATIONS_PATH, [])
        self.corrections: list = load_json(CORRECTIONS_PATH, [])
        self.preferences: dict = load_json(PREFERENCES_PATH, {})
        self.knowledge_base: dict = load_json(KNOWLEDGE_BASE_PATH, {})
        self.fine_tune_data: list = load_json(FINE_TUNE_PATH, [])

        session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.current_session = {
            "id": session_id,
            "date": datetime.now().isoformat(),
            "messages": [],
            "apps_launched": [],
            "intents_used": [],
        }
        self.current_conversation_id = self._new_conversation_id()
        self.current_conversation = {
            "id": self.current_conversation_id,
            "title": "Nouvelle conversation",
            "date": datetime.now().isoformat(),
            "messages": [],
        }
        self._auto_save_running = False

        logger.info(
            "Mémoire chargée: %d sessions, %d conversations, %d messages au total",
            len(self.sessions),
            len(self.conversations),
            self.profile.get("total_messages", 0),
        )
        self.start_auto_save()

    def _new_conversation_id(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _auto_save_loop(self) -> None:
        while self._auto_save_running:
            time.sleep(60)
            if not self._auto_save_running:
                break
            try:
                self._save_all()
                logger.debug("Auto-save mémoire effectuée")
            except Exception as exc:
                logger.error("Erreur auto-save: %s", exc)

    def start_auto_save(self) -> None:
        if self._auto_save_running:
            return
        self._auto_save_running = True
        threading.Thread(target=self._auto_save_loop, daemon=True).start()
        logger.info("Auto-save mémoire démarré (toutes les 60s)")

    def _save_all(self) -> None:
        save_json(SESSIONS_PATH, self.sessions)
        save_json(CONVERSATIONS_PATH, self.conversations)
        save_json(PROFILE_PATH, self.profile)
        save_json(PATTERNS_PATH, self.patterns)
        save_json(FINE_TUNE_PATH, self.patterns.get("quality_exchanges", []))
        save_json(CORRECTIONS_PATH, self.corrections)
        save_json(PREFERENCES_PATH, self.preferences)
        save_json(KNOWLEDGE_BASE_PATH, self.knowledge_base)
        logger.info(
            "Mémoire complète sauvegardée — %d sessions, %d convs, %d messages",
            len(self.sessions),
            len(self.conversations),
            self.profile.get("total_messages", 0),
        )

    def add_to_conversation(self, role: str, text: str) -> None:
        self.current_conversation["messages"].append({
            "role": role,
            "text": text,
            "time": datetime.now().isoformat(),
        })
        if role == "user" and self.current_conversation["title"] == "Nouvelle conversation":
            self.current_conversation["title"] = text[:40] + ("..." if len(text) > 40 else "")
        self.save_current_conversation()
        save_json(PROFILE_PATH, self.profile)

    def save_current_conversation(self) -> None:
        if not self.current_conversation["messages"]:
            return
        snapshot = copy.deepcopy(self.current_conversation)
        for i, conv in enumerate(self.conversations):
            if conv["id"] == self.current_conversation_id:
                self.conversations[i] = snapshot
                break
        else:
            self.conversations.append(snapshot)
        save_json(CONVERSATIONS_PATH, self.conversations)

    def new_conversation(self) -> str:
        self.save_current_conversation()
        self.current_conversation_id = self._new_conversation_id()
        self.current_conversation = {
            "id": self.current_conversation_id,
            "title": "Nouvelle conversation",
            "date": datetime.now().isoformat(),
            "messages": [],
        }
        return self.current_conversation_id

    def get_conversations_list(self) -> list:
        return list(reversed([
            {
                "id": c["id"],
                "title": c.get("title", "Conversation"),
                "date": c.get("date", "")[:10],
                "count": len(c.get("messages", [])),
            }
            for c in self.conversations
        ]))

    def load_conversation(self, conv_id: str) -> list:
        for conv in self.conversations:
            if conv["id"] == conv_id:
                return conv.get("messages", [])
        return []

    def record_message(self, role: str, text: str, intent: str | None = None, model: str | None = None) -> None:
        entry = {
            "role": role,
            "text": text[:500],
            "time": datetime.now().isoformat(),
        }
        if intent:
            entry["intent"] = intent
            self.profile["frequent_commands"][intent] = self.profile["frequent_commands"].get(intent, 0) + 1
        if model:
            entry["model"] = model
        self.current_session["messages"].append(entry)
        self.profile["total_messages"] = self.profile.get("total_messages", 0) + 1
        self.profile["last_use"] = datetime.now().isoformat()
        if not self.profile.get("first_use"):
            self.profile["first_use"] = self.profile["last_use"]
        if role == "assistant":
            self.profile["total_tokens_generated"] = self.profile.get("total_tokens_generated", 0) + len(text.split())
        save_json(PROFILE_PATH, self.profile)

    def record_app_launch(self, app: str) -> None:
        self.current_session["apps_launched"].append(app)
        self.profile["frequent_apps"][app] = self.profile["frequent_apps"].get(app, 0) + 1
        last = self.profile.setdefault("last_apps_opened", [])
        last.append(app)
        self.profile["last_apps_opened"] = last[-10:]
        hour_key = str(datetime.now().hour)
        app_times = self.profile.setdefault("app_time_of_day", {})
        if app not in app_times:
            app_times[app] = {}
        app_times[app][hour_key] = app_times[app].get(hour_key, 0) + 1
        save_json(PROFILE_PATH, self.profile)

    def record_intent(self, intent: str) -> None:
        self.current_session["intents_used"].append(intent)
        self.profile["frequent_commands"][intent] = self.profile["frequent_commands"].get(intent, 0) + 1
        if intent.startswith("aviation_metar"):
            self.profile.setdefault("aviation", {})["total_metar_requests"] = (
                self.profile.get("aviation", {}).get("total_metar_requests", 0) + 1
            )
        save_json(PROFILE_PATH, self.profile)

    def extract_preferences(self, user_text: str, aria_response: str) -> None:
        text_lower = user_text.lower()
        if any(w in text_lower for w in ["j'aime", "j'adore", "super", "parfait", "excellent", "merci", "génial"]):
            self.profile["positive_feedback_count"] = self.profile.get("positive_feedback_count", 0) + 1
        if any(w in text_lower for w in ["non", "pas ça", "mauvais", "faux", "incorrect", "c'est pas"]):
            self.profile["negative_feedback_count"] = self.profile.get("negative_feedback_count", 0) + 1
            self.profile["correction_count"] = self.profile.get("correction_count", 0) + 1
            self.corrections.append({
                "input": user_text[:200],
                "response": aria_response[:200],
                "time": datetime.now().isoformat(),
            })
            save_json(CORRECTIONS_PATH, self.corrections)
        topics = {
            "aviation": ["vol", "metar", "pilote", "avion", "dr400", "lfrs"],
            "gaming": ["jeu", "msfs", "steam", "valorant", "aoe"],
            "maths": ["calcul", "dérive", "intégrale", "équation"],
            "code": ["code", "python", "script", "fonction", "cursor"],
        }
        for topic, keywords in topics.items():
            if any(k in text_lower for k in keywords):
                self.profile["frequent_topics"][topic] = self.profile["frequent_topics"].get(topic, 0) + 1
        save_json(PROFILE_PATH, self.profile)

    def analyze_conversation_quality(self, user_msg: str, aria_response: str) -> float:
        score = 0.5
        words = len(aria_response.split())
        if 20 < words < 200:
            score += 0.1
        positive = ["merci", "super", "parfait", "cool", "génial", "ok", "bien"]
        if any(w in user_msg.lower() for w in positive):
            score += 0.2
        return min(1.0, max(0.0, score))

    def detect_implicit_preferences(self, messages_window: list[dict]) -> None:
        for msg in messages_window:
            text = msg.get("text", msg.get("content", "")).lower()
            if any(w in text for w in ["développe", "explique plus", "donne plus de détails"]):
                self.profile["prefers_detailed_answers"] = True
            if any(w in text for w in ["😂", "lol", "mdr", "haha"]):
                self.profile["prefers_humor"] = True
            if any(w in text for w in ["algorithme", "complexité", "architecture", "protocole"]):
                self.profile["prefers_technical"] = True
        save_json(PROFILE_PATH, self.profile)

    def detect_command_sequences(self) -> None:
        intents = self.current_session.get("intents_used", [])
        if len(intents) < 2:
            return
        sequences = self.patterns.setdefault("command_sequences", [])
        for i in range(len(intents) - 1):
            seq_key = f"{intents[i]}->{intents[i + 1]}"
            if seq_key not in sequences:
                sequences.append(seq_key)
        save_json(PATTERNS_PATH, self.patterns)

    def get_proactive_suggestions(self) -> list[str]:
        suggestions: list[str] = []
        hour = datetime.now().hour
        top_apps_at_hour: dict[str, int] = {}
        for app, times in self.profile.get("app_time_of_day", {}).items():
            hour_key = str(hour)
            if times.get(hour_key, 0) > 3:
                top_apps_at_hour[app] = times[hour_key]
        if top_apps_at_hour:
            top = max(top_apps_at_hour, key=top_apps_at_hour.get)
            suggestions.append(f"Tu lances souvent {top} à cette heure")
        return suggestions

    def build_personalized_system_prompt(self) -> str:
        profile = self.profile
        patterns = self.patterns
        sessions = profile.get("total_sessions", len(self.sessions))
        messages = profile.get("total_messages", 0)
        top_apps = sorted(profile.get("frequent_apps", {}).items(), key=lambda x: x[1], reverse=True)[:5]
        top_topics = sorted(profile.get("frequent_topics", {}).items(), key=lambda x: x[1], reverse=True)[:4]
        style = patterns.get("optimal_response_style", {})
        satisfaction = profile.get("satisfaction_score", 0.5)
        corrections = profile.get("correction_count", 0)
        aviation = profile.get("aviation", DEFAULT_PROFILE["aviation"])
        school = profile.get("school", DEFAULT_PROFILE["school"])
        voice_shortcuts = patterns.get("voice_shortcuts", {})

        prompt = f"""
CONTEXTE APPRIS SUR L'UTILISATEUR ({sessions} sessions, {messages} messages échangés):

IDENTITÉ: {profile.get('name', 'mathi')}, {profile.get('age_group', '')}, {profile.get('location', '')}

APPLICATIONS FAVORITES (par fréquence):
{chr(10).join(f"- {app}: utilisé {count}x" for app, count in top_apps) or "- Aucune donnée encore"}

SUJETS D'INTÉRÊT (par fréquence):
{chr(10).join(f"- {topic}: {count}x" for topic, count in top_topics) or "- Aucune donnée encore"}

STYLE DE RÉPONSE OPTIMAL DÉTECTÉ:
- Longueur: {"détaillée" if profile.get("prefers_detailed_answers") else "normale"}
- Humour: {"oui" if profile.get("prefers_humor") else "non"}
- Technique: {"oui" if profile.get("prefers_technical") else "non"}
- Exemples: {"oui" if profile.get("prefers_examples", True) else "non"}
- Max phrases recommandé: {style.get("max_sentences", 6)}

AVIATION:
- Appareil: {aviation.get("aircraft", "")}
- Base: {aviation.get("home_base", "")}
- Licence: {aviation.get("license", "")}
- Requêtes METAR: {aviation.get("total_metar_requests", 0)}x

SCOLAIRE:
- Niveau: {school.get("level", "")}
- Spécialités: {", ".join(school.get("specialties", []))}
- BAC: {school.get("bac_date", "")}

QUALITÉ:
- Score satisfaction: {satisfaction:.0%}
- Corrections effectuées: {corrections}
{"- ATTENTION: l'utilisateur a souvent dû corriger les réponses, sois plus précis." if corrections > 5 else ""}

RACCOURCIS VOCAUX APPRIS:
{chr(10).join(f'- "{trigger}" → {action}' for trigger, action in list(voice_shortcuts.items())[:5]) or "- Aucun encore"}
"""
        suggestions = self.get_proactive_suggestions()
        if suggestions:
            prompt += "\n\nSUGGESTIONS PROACTIVES:\n" + "\n".join(f"- {s}" for s in suggestions)
        return prompt.strip()

    def get_context_for_llm(self) -> str:
        return self.build_personalized_system_prompt()

    def get_style_hint(self) -> str:
        corrections = self.profile.get("correction_count", 0)
        pos = self.profile.get("positive_feedback_count", 0)
        if corrections > 5:
            return "Sois très précis et vérifie bien tes réponses, l'utilisateur a corrigé plusieurs erreurs."
        if pos > 10:
            return "L'utilisateur apprécie tes réponses, continue dans ce style."
        if self.profile.get("prefers_detailed_answers"):
            return "L'utilisateur préfère des réponses détaillées et développées."
        return ""

    def record_fine_tune_example(self, user_input: str, aria_output: str, quality_score: float) -> None:
        if quality_score < 0.7:
            return
        example = {
            "input": user_input,
            "output": aria_output,
            "score": quality_score,
            "date": datetime.now().isoformat(),
            "context": {
                "model": "qwen3:14b",
                "topic": self._detect_topic(user_input),
            },
        }
        exchanges = self.patterns.setdefault("quality_exchanges", [])
        exchanges.append(example)
        self.fine_tune_data = exchanges
        save_json(PATTERNS_PATH, self.patterns)
        save_json(FINE_TUNE_PATH, exchanges)

    def export_fine_tune_dataset(self) -> str:
        output_path = app_paths.data_dir() / "fine_tune_dataset.jsonl"
        examples = self.patterns.get("quality_exchanges", [])
        with output_path.open("w", encoding="utf-8") as f:
            for ex in examples:
                line = {
                    "messages": [
                        {"role": "user", "content": ex["input"]},
                        {"role": "assistant", "content": ex["output"]},
                    ]
                }
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return str(output_path)

    def _detect_topic(self, text: str) -> str:
        topics = {
            "aviation": ["vol", "metar", "avion", "pilote", "décollage"],
            "maths": ["calcul", "dérive", "intégrale", "équation", "probabilité"],
            "gaming": ["jeu", "msfs", "steam", "valorant"],
            "code": ["code", "python", "fonction", "script"],
            "general": [],
        }
        text_lower = text.lower()
        for topic, keywords in topics.items():
            if topic != "general" and any(k in text_lower for k in keywords):
                return topic
        return "general"

    def update_active_hours(self) -> None:
        hour = str(datetime.now().hour)
        day = datetime.now().strftime("%A").lower()
        self.profile.setdefault("active_hours", {})[hour] = self.profile["active_hours"].get(hour, 0) + 1
        self.profile.setdefault("active_days", {})[day] = self.profile["active_days"].get(day, 0) + 1
        if self.profile["active_hours"]:
            self.profile["peak_hour"] = max(
                self.profile["active_hours"],
                key=self.profile["active_hours"].get,
            )
        save_json(PROFILE_PATH, self.profile)

    def get_memory_stats(self) -> dict:
        frequent_apps = self.profile.get("frequent_apps", {})
        frequent_topics = self.profile.get("frequent_topics", {})
        return {
            "total_sessions": max(self.profile.get("total_sessions", 0), len(self.sessions)),
            "total_messages": self.profile.get("total_messages", 0),
            "top_app": max(frequent_apps, key=frequent_apps.get) if frequent_apps else None,
            "top_topic": max(frequent_topics, key=frequent_topics.get) if frequent_topics else None,
            "satisfaction": f"{self.profile.get('satisfaction_score', 0):.0%}",
            "corrections": self.profile.get("correction_count", 0),
            "fine_tune_examples": len(self.patterns.get("quality_exchanges", [])),
            "conversations_saved": len(self.conversations),
            "peak_hour": self.profile.get("peak_hour"),
            "voice_shortcuts": len(self.patterns.get("voice_shortcuts", {})),
        }

    def save_session(self) -> None:
        if not self.current_session.get("messages"):
            return
        self.current_session["end_time"] = datetime.now().isoformat()
        self.current_session["duration_messages"] = len(self.current_session["messages"])
        session_id = self.current_session.get("id")
        found = False
        for i, session in enumerate(self.sessions):
            if session.get("id") == session_id or session.get("date") == self.current_session.get("date"):
                self.sessions[i] = copy.deepcopy(self.current_session)
                found = True
                break
        if not found:
            self.sessions.append(copy.deepcopy(self.current_session))
        self.profile["total_sessions"] = len(self.sessions)
        self.profile["last_use"] = datetime.now().isoformat()
        if not self.profile.get("first_use"):
            self.profile["first_use"] = self.profile["last_use"]
        if self.sessions:
            lengths = [s.get("duration_messages", len(s.get("messages", []))) for s in self.sessions]
            self.profile["average_session_length"] = sum(lengths) / len(lengths)
        self._save_all()
        logger.info("Session sauvegardée. Total: %d sessions", len(self.sessions))

    def get_top_apps(self, n: int = 5) -> list[str]:
        return [
            app for app, _ in sorted(
                self.profile.get("frequent_apps", {}).items(),
                key=lambda x: x[1],
                reverse=True,
            )[:n]
        ]

    def reset_all(self) -> None:
        self.profile = copy.deepcopy(DEFAULT_PROFILE)
        self.patterns = copy.deepcopy(DEFAULT_PATTERNS)
        self.conversations = []
        self.sessions = []
        self.corrections = []
        self.preferences = {}
        self.knowledge_base = {}
        self.fine_tune_data = []
        self.current_session = {
            "id": datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
            "date": datetime.now().isoformat(),
            "messages": [],
            "apps_launched": [],
            "intents_used": [],
        }
        self.current_conversation_id = self._new_conversation_id()
        self.current_conversation = {
            "id": self.current_conversation_id,
            "title": "Nouvelle conversation",
            "date": datetime.now().isoformat(),
            "messages": [],
        }
        self._save_all()


_engine: MemoryEngine | None = None


def get_engine() -> MemoryEngine:
    global _engine
    if _engine is None:
        _engine = MemoryEngine()
    return _engine


def record_message(role, text, intent=None, model=None):
    get_engine().record_message(role, text, intent, model)


def record_app_launch(app):
    get_engine().record_app_launch(app)


def record_intent(intent: str) -> None:
    get_engine().record_intent(intent)


def extract_preferences(user_text, aria_response):
    get_engine().extract_preferences(user_text, aria_response)


def get_context_for_llm() -> str:
    return get_engine().get_context_for_llm()


def get_style_hint() -> str:
    return get_engine().get_style_hint()


def save_session() -> None:
    get_engine().save_session()


def get_top_apps(n=5) -> list[str]:
    return get_engine().get_top_apps(n)


def add_to_conversation(role: str, text: str) -> None:
    get_engine().add_to_conversation(role, text)


def new_conversation() -> str:
    return get_engine().new_conversation()


def get_conversations_list() -> list:
    return get_engine().get_conversations_list()


def load_conversation(conv_id: str) -> list:
    return get_engine().load_conversation(conv_id)


def save_current_conversation() -> None:
    get_engine().save_current_conversation()


def update_active_hours():
    get_engine().update_active_hours()


def build_personalized_system_prompt() -> str:
    return get_engine().build_personalized_system_prompt()


def analyze_conversation_quality(user_msg, aria_response):
    return get_engine().analyze_conversation_quality(user_msg, aria_response)


def record_fine_tune_example(user_input, aria_output, quality_score):
    get_engine().record_fine_tune_example(user_input, aria_output, quality_score)


def detect_implicit_preferences(messages_window):
    get_engine().detect_implicit_preferences(messages_window)


def detect_command_sequences():
    get_engine().detect_command_sequences()


def get_memory_stats() -> dict:
    return get_engine().get_memory_stats()


def export_fine_tune() -> str:
    return get_engine().export_fine_tune_dataset()


def export_fine_tune_dataset():
    return export_fine_tune()


def reset_memory() -> None:
    get_engine().reset_all()
