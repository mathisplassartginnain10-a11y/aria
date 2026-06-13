# Assistant Vocal — Spec v12 : Système de mémoire et d'apprentissage avancé

## Vision
ARIA doit apprendre de chaque interaction pour devenir de plus en plus personnalisé.
Après 100 conversations, ARIA doit connaître l'utilisateur mieux qu'un ami proche.

---

## Architecture des fichiers de données

```
data/
├── conversations.json      # Toutes les conversations (max 500)
├── sessions.json           # Métadonnées des sessions
├── user_profile.json       # Profil appris de l'utilisateur
├── learned_patterns.json   # Patterns détectés automatiquement
├── fine_tune_data.json     # Données pour fine-tuning futur
├── corrections.json        # Corrections explicites de l'utilisateur
├── preferences.json        # Préférences détectées et explicites
└── knowledge_base.json     # Base de connaissances personnalisée
```

---

## memory_engine.py — Version complète

### UserProfile
```python
DEFAULT_PROFILE = {
    # Identité
    "name": "mathi",
    "age_group": "lycéen",
    "location": "Couëron, France",
    
    # Statistiques globales
    "total_sessions": 0,
    "total_messages": 0,
    "total_tokens_generated": 0,
    "first_use": None,
    "last_use": None,
    "average_session_length": 0,
    
    # Apps
    "frequent_apps": {},          # {"msfs": 47, "spotify": 23, ...}
    "app_time_of_day": {},        # {"msfs": {"morning": 2, "evening": 15}, ...}
    "last_apps_opened": [],       # 10 dernières apps
    
    # Sujets et intérêts
    "frequent_topics": {},        # {"aviation": 89, "maths": 34, ...}
    "topic_depth": {},            # {"aviation": "expert", "maths": "intermédiaire"}
    "interests_detected": [],     # Détectés automatiquement
    
    # Comportement conversationnel
    "frequent_commands": {},      # {"lancer_app": 67, "question_libre": 45, ...}
    "preferred_response_length": "normal",
    "preferred_language_style": "casual",  # casual/formal/technical
    "uses_voice": True,
    "uses_text": True,
    "voice_vs_text_ratio": 0.5,
    
    # Qualité des réponses
    "positive_feedback_count": 0,
    "negative_feedback_count": 0,
    "correction_count": 0,
    "satisfaction_score": 0.0,    # 0-1, calculé automatiquement
    
    # Horaires
    "active_hours": {},           # {"08": 5, "14": 12, "20": 34, ...}
    "active_days": {},            # {"lundi": 12, "samedi": 34, ...}
    "peak_hour": None,
    
    # Préférences détectées
    "prefers_detailed_answers": False,
    "prefers_examples": True,
    "prefers_humor": False,
    "prefers_technical": False,
    
    # Vocabulaire personnalisé
    "custom_vocabulary": {},      # Mots/expressions fréquents
    "custom_shortcuts": {},       # {"msfs": "Microsoft Flight Simulator 2024"}
    
    # Aviation spécifique
    "aviation": {
        "aircraft": "Robin DR400",
        "home_base": "LFRS",
        "license": "PPL en cours",
        "total_metar_requests": 0,
        "frequent_destinations": {},
    },
    
    # Contexte scolaire
    "school": {
        "level": "Première",
        "specialties": ["Maths", "Allemand"],
        "bac_date": "2026",
        "frequent_subjects": {},
    },
    
    # Gaming
    "gaming": {
        "favorite_games": {},
        "session_count": {},
    }
}
```

### LearnedPatterns
```python
DEFAULT_PATTERNS = {
    # Raccourcis vocaux appris
    "voice_shortcuts": {},        # {"lance le sim": "lancer_app:msfs"}
    
    # Corrections mémorisées
    "intent_corrections": {},     # {"cherche météo": "aviation_metar" (corrigé de search_web)}
    
    # Style de réponse optimal détecté
    "optimal_response_style": {
        "max_sentences": 6,
        "use_examples": True,
        "use_humor": False,
        "technical_level": "intermediate",
        "avoid_bullet_points_in_voice": True,
    },
    
    # Chaînes de commandes fréquentes
    "command_sequences": [],      # [["lancer_app:msfs", "aviation_metar:LFRS"], ...]
    
    # Associations apprises
    "topic_app_associations": {}, # {"vol": ["msfs"], "musique": ["spotify"]}
    
    # Horaires détectés
    "schedule_patterns": {
        "morning_routine": [],    # Commandes du matin
        "evening_routine": [],    # Commandes du soir
    },
    
    # Fine-tuning data (paires input/output de qualité)
    "quality_exchanges": [],      # Max 1000 échanges notés positifs
}
```

### Méthodes d'apprentissage avancées

```python
class MemoryEngine:

    def analyze_conversation_quality(self, user_msg: str, aria_response: str) -> float:
        """
        Score de qualité 0-1 basé sur :
        - Longueur de la réponse vs longueur demandée
        - Présence de mots positifs dans le message suivant
        - Absence de correction dans le message suivant
        - Cohérence avec le sujet
        """
        score = 0.5  # neutre par défaut
        
        # Réponse trop courte ou trop longue
        words = len(aria_response.split())
        if 20 < words < 200:
            score += 0.1
        
        # Vocabulaire positif dans le contexte
        positive = ["merci", "super", "parfait", "cool", "génial", "ok", "bien"]
        if any(w in user_msg.lower() for w in positive):
            score += 0.2
            
        return min(1.0, max(0.0, score))

    def detect_implicit_preferences(self, messages_window: list[dict]):
        """
        Analyse une fenêtre de messages pour détecter des préférences implicites.
        - Si l'utilisateur demande souvent "développe" → prefers_detailed_answers = True
        - Si l'utilisateur utilise des émojis → prefers_humor = True
        - Si l'utilisateur pose des questions techniques → prefers_technical = True
        """
        for msg in messages_window:
            text = msg.get("text", "").lower()
            if any(w in text for w in ["développe", "explique plus", "donne plus de détails"]):
                self.profile["prefers_detailed_answers"] = True
            if any(w in text for w in ["😂", "lol", "mdr", "haha"]):
                self.profile["prefers_humor"] = True
            if any(w in text for w in ["algorithme", "complexité", "architecture", "protocole"]):
                self.profile["prefers_technical"] = True

    def detect_command_sequences(self):
        """
        Détecte les séquences de commandes fréquentes pour les anticiper.
        Ex: "lance MSFS" → toujours suivi de "METAR LFRS"
        → Proposer automatiquement le METAR après avoir lancé MSFS
        """
        if len(self.current_session["intents_used"]) >= 2:
            for i in range(len(self.current_session["intents_used"]) - 1):
                seq = (
                    self.current_session["intents_used"][i],
                    self.current_session["intents_used"][i+1]
                )
                seq_key = f"{seq[0]}->{seq[1]}"
                count = self.patterns["command_sequences"].count(seq_key)
                # Si séquence vue 3+ fois, la noter
                if seq_key not in self.patterns["command_sequences"]:
                    self.patterns["command_sequences"].append(seq_key)

    def get_proactive_suggestions(self) -> list[str]:
        """
        Retourne des suggestions proactives basées sur les patterns.
        Ex: Si c'est le soir et que d'habitude l'utilisateur lance Discord → suggérer
        """
        from datetime import datetime
        suggestions = []
        hour = datetime.now().hour
        
        # Heure habituelle d'activité
        top_apps_at_hour = {}
        for app, times in self.profile.get("app_time_of_day", {}).items():
            hour_key = str(hour)
            if times.get(hour_key, 0) > 3:
                top_apps_at_hour[app] = times[hour_key]
        
        if top_apps_at_hour:
            top = max(top_apps_at_hour, key=top_apps_at_hour.get)
            suggestions.append(f"Tu lances souvent {top} à cette heure")
        
        return suggestions

    def build_personalized_system_prompt(self) -> str:
        """
        Construit un system prompt ultra-personnalisé basé sur tout l'historique appris.
        """
        profile = self.profile
        patterns = self.patterns
        
        # Stats
        sessions = profile["total_sessions"]
        messages = profile["total_messages"]
        
        # Top apps
        top_apps = sorted(profile["frequent_apps"].items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Top sujets
        top_topics = sorted(profile["frequent_topics"].items(), key=lambda x: x[1], reverse=True)[:4]
        
        # Style optimal
        style = patterns.get("optimal_response_style", {})
        
        # Satisfaction
        satisfaction = profile.get("satisfaction_score", 0.5)
        
        # Corrections passées
        corrections = profile.get("correction_count", 0)
        
        prompt = f"""
CONTEXTE APPRIS SUR L'UTILISATEUR ({sessions} sessions, {messages} messages échangés):

IDENTITÉ: {profile['name']}, {profile['age_group']}, {profile['location']}

APPLICATIONS FAVORITES (par fréquence):
{chr(10).join(f"- {app}: utilisé {count}x" for app, count in top_apps) or "- Aucune donnée encore"}

SUJETS D'INTÉRÊT (par fréquence):
{chr(10).join(f"- {topic}: {count}x" for topic, count in top_topics) or "- Aucune donnée encore"}

STYLE DE RÉPONSE OPTIMAL DÉTECTÉ:
- Longueur: {"détaillée" if profile.get("prefers_detailed_answers") else "normale"}
- Humour: {"oui" if profile.get("prefers_humor") else "non"}
- Technique: {"oui" if profile.get("prefers_technical") else "non"}
- Exemples: {"oui" if profile.get("prefers_examples") else "non"}
- Max phrases recommandé: {style.get("max_sentences", 6)}

AVIATION:
- Appareil: {profile["aviation"]["aircraft"]}
- Base: {profile["aviation"]["home_base"]}
- Licence: {profile["aviation"]["license"]}
- Requêtes METAR: {profile["aviation"]["total_metar_requests"]}x

SCOLAIRE:
- Niveau: {profile["school"]["level"]}
- Spécialités: {", ".join(profile["school"]["specialties"])}
- BAC: {profile["school"]["bac_date"]}

QUALITÉ:
- Score satisfaction: {satisfaction:.0%}
- Corrections effectuées: {corrections}
{"- ATTENTION: l'utilisateur a souvent dû corriger les réponses, sois plus précis." if corrections > 5 else ""}

RACCOURCIS VOCAUX APPRIS:
{chr(10).join(f'- "{trigger}" → {action}' for trigger, action in list(patterns.get("voice_shortcuts", {}).items())[:5]) or "- Aucun encore"}
"""
        return prompt.strip()

    def record_fine_tune_example(self, user_input: str, aria_output: str, quality_score: float):
        """
        Sauvegarde les meilleurs échanges pour un futur fine-tuning local.
        Format compatible avec Ollama modelfile / Unsloth.
        """
        if quality_score >= 0.7:
            example = {
                "input": user_input,
                "output": aria_output,
                "score": quality_score,
                "date": datetime.now().isoformat(),
                "context": {
                    "model": "qwen3:14b",
                    "topic": self._detect_topic(user_input),
                }
            }
            self.patterns["quality_exchanges"].append(example)
            if len(self.patterns["quality_exchanges"]) > 1000:
                # Garder les 1000 meilleurs
                self.patterns["quality_exchanges"] = sorted(
                    self.patterns["quality_exchanges"],
                    key=lambda x: x["score"],
                    reverse=True
                )[:1000]

    def export_fine_tune_dataset(self) -> str:
        """
        Exporte les données en format JSONL pour fine-tuning avec Unsloth/Ollama.
        """
        output_path = app_paths.data_dir() / "fine_tune_dataset.jsonl"
        examples = self.patterns.get("quality_exchanges", [])
        with output_path.open("w", encoding="utf-8") as f:
            for ex in examples:
                line = {
                    "messages": [
                        {"role": "user", "content": ex["input"]},
                        {"role": "assistant", "content": ex["output"]}
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
            "general": []
        }
        text_lower = text.lower()
        for topic, keywords in topics.items():
            if any(k in text_lower for k in keywords):
                return topic
        return "general"

    def update_active_hours(self):
        """Met à jour les stats d'utilisation par heure."""
        from datetime import datetime
        hour = str(datetime.now().hour)
        day = datetime.now().strftime("%A").lower()
        self.profile["active_hours"][hour] = self.profile["active_hours"].get(hour, 0) + 1
        self.profile["active_days"][day] = self.profile["active_days"].get(day, 0) + 1
        
        # Recalculer l'heure de pointe
        if self.profile["active_hours"]:
            self.profile["peak_hour"] = max(self.profile["active_hours"], key=self.profile["active_hours"].get)

    def get_memory_stats(self) -> dict:
        """Retourne des stats complètes pour l'affichage dans l'UI."""
        return {
            "total_sessions": self.profile["total_sessions"],
            "total_messages": self.profile["total_messages"],
            "top_app": max(self.profile["frequent_apps"], key=self.profile["frequent_apps"].get) if self.profile["frequent_apps"] else None,
            "top_topic": max(self.profile["frequent_topics"], key=self.profile["frequent_topics"].get) if self.profile["frequent_topics"] else None,
            "satisfaction": f"{self.profile.get('satisfaction_score', 0):.0%}",
            "corrections": self.profile.get("correction_count", 0),
            "fine_tune_examples": len(self.patterns.get("quality_exchanges", [])),
            "conversations_saved": len(self.conversations),
            "peak_hour": self.profile.get("peak_hour"),
            "voice_shortcuts": len(self.patterns.get("voice_shortcuts", {})),
        }
```

---

## Intégration dans llm.py

```python
# Dans ask(text):
# 1. Mettre à jour les stats d'utilisation
memory_engine.get_engine().update_active_hours()

# 2. Injecter le system prompt personnalisé
personalized_ctx = memory_engine.get_engine().build_personalized_system_prompt()
dynamic_system = BASE_SYSTEM_PROMPT + "\n\n" + personalized_ctx

# 3. Après la réponse, analyser la qualité
quality = memory_engine.get_engine().analyze_conversation_quality(text, full_response)

# 4. Sauvegarder pour fine-tuning si qualité suffisante
memory_engine.get_engine().record_fine_tune_example(text, full_response, quality)

# 5. Mettre à jour les patterns
memory_engine.get_engine().detect_implicit_preferences(history[-6:])

# 6. Mettre à jour satisfaction_score (moyenne mobile)
engine = memory_engine.get_engine()
old_score = engine.profile.get("satisfaction_score", 0.5)
engine.profile["satisfaction_score"] = old_score * 0.95 + quality * 0.05

# 7. Sauvegarder conversation
memory_engine.add_to_conversation('assistant', full_response)
memory_engine.save_current_conversation()
```

---

## Affichage dans l'UI — Section Mémoire

Dans les paramètres, ajouter une section "Mémoire & Apprentissage" :

```javascript
async loadMemoryStats() {
    const raw = await this.api('get_memory_stats');
    const stats = JSON.parse(raw || '{}');
    document.getElementById('mem-sessions').textContent = stats.total_sessions || 0;
    document.getElementById('mem-messages').textContent = stats.total_messages || 0;
    document.getElementById('mem-top-app').textContent = stats.top_app || '—';
    document.getElementById('mem-top-topic').textContent = stats.top_topic || '—';
    document.getElementById('mem-satisfaction').textContent = stats.satisfaction || '—';
    document.getElementById('mem-corrections').textContent = stats.corrections || 0;
    document.getElementById('mem-finetune').textContent = stats.fine_tune_examples || 0;
    document.getElementById('mem-convs').textContent = stats.conversations_saved || 0;
    document.getElementById('mem-peak').textContent = stats.peak_hour ? `${stats.peak_hour}h` : '—';
    document.getElementById('mem-shortcuts').textContent = stats.voice_shortcuts || 0;
}
```

HTML dans settings :
```html
<div class="settings-section">
  <div class="settings-title">Mémoire & Apprentissage</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">
    <div class="stat-card"><div class="stat-val" id="mem-sessions">—</div><div class="stat-label">Sessions</div></div>
    <div class="stat-card"><div class="stat-val" id="mem-messages">—</div><div class="stat-label">Messages</div></div>
    <div class="stat-card"><div class="stat-val" id="mem-top-app">—</div><div class="stat-label">App fav.</div></div>
    <div class="stat-card"><div class="stat-val" id="mem-top-topic">—</div><div class="stat-label">Sujet fav.</div></div>
    <div class="stat-card"><div class="stat-val" id="mem-satisfaction">—</div><div class="stat-label">Satisfaction</div></div>
    <div class="stat-card"><div class="stat-val" id="mem-finetune">—</div><div class="stat-label">Exemples IA</div></div>
    <div class="stat-card"><div class="stat-val" id="mem-convs">—</div><div class="stat-label">Conversations</div></div>
    <div class="stat-card"><div class="stat-val" id="mem-peak">—</div><div class="stat-label">Heure active</div></div>
  </div>
  <button class="settings-btn" onclick="aria.api('export_fine_tune').then(p => aria.showToast('Exporté: ' + p, 'success'))">
    Exporter dataset fine-tuning
  </button>
  <button class="settings-btn" onclick="aria.api('open_file', 'data/user_profile.json')">
    Voir profil complet
  </button>
  <button class="settings-btn" onclick="aria.api('open_file', 'data/learned_patterns.json')">
    Voir patterns appris
  </button>
  <button class="settings-btn" style="color:var(--error);border-color:var(--error)" 
    onclick="if(confirm('Effacer toute la mémoire ?')) aria.api('reset_memory').then(() => aria.showToast('Mémoire effacée','success'))">
    Réinitialiser la mémoire
  </button>
</div>
```

CSS stats cards :
```css
.stat-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  text-align: center;
}
.stat-val { font-size: 16px; font-weight: 600; color: var(--accent); }
.stat-label { font-size: 10px; color: var(--text3); margin-top: 2px; }
```

---

## Nouvelles méthodes AriaAPI dans ui.py

```python
def get_memory_stats(self) -> str:
    import json, memory_engine
    return json.dumps(memory_engine.get_engine().get_memory_stats())

def export_fine_tune(self) -> str:
    import memory_engine
    return memory_engine.get_engine().export_fine_tune_dataset()

def reset_memory(self) -> None:
    import memory_engine, app_paths, json
    engine = memory_engine.get_engine()
    engine.profile = dict(memory_engine.DEFAULT_PROFILE)
    engine.patterns = dict(memory_engine.DEFAULT_PATTERNS)
    engine.conversations = []
    engine.sessions = []
    memory_engine.save_json(memory_engine.PROFILE_PATH, engine.profile)
    memory_engine.save_json(memory_engine.PATTERNS_PATH, engine.patterns)
    memory_engine.save_json(memory_engine.CONVERSATIONS_PATH, [])
    memory_engine.save_json(memory_engine.SESSIONS_PATH, [])

def add_voice_shortcut(self, trigger: str, action: str) -> None:
    import memory_engine
    engine = memory_engine.get_engine()
    engine.patterns["voice_shortcuts"][trigger.lower()] = action
    memory_engine.save_json(memory_engine.PATTERNS_PATH, engine.patterns)
```

---

## Prompt Cursor

> Implement the complete advanced memory and learning system from this v12 spec.
>
> FILE 1 — Rewrite memory_engine.py completely with:
> - DEFAULT_PROFILE and DEFAULT_PATTERNS dicts as specified
> - MemoryEngine class with all methods: analyze_conversation_quality, detect_implicit_preferences, detect_command_sequences, get_proactive_suggestions, build_personalized_system_prompt, record_fine_tune_example, export_fine_tune_dataset, _detect_topic, update_active_hours, get_memory_stats, add_to_conversation, new_conversation, save_current_conversation, get_conversations_list, load_conversation
> - Singleton get_engine() function
> - Module-level wrapper functions for all methods
> - Save all 5 data files: sessions, conversations, profile, patterns, fine_tune_data
>
> FILE 2 — Update llm.py ask() to:
> - Call update_active_hours() at start
> - Use build_personalized_system_prompt() to inject dynamic context
> - Call analyze_conversation_quality() after response
> - Call record_fine_tune_example() if quality >= 0.7
> - Call detect_implicit_preferences() on recent history
> - Update satisfaction_score with exponential moving average
> - Call add_to_conversation() for both user and assistant messages
> - Call save_current_conversation() after each exchange
>
> FILE 3 — Update ui.py AriaAPI with new methods:
> get_memory_stats, export_fine_tune, reset_memory, add_voice_shortcut
>
> FILE 4 — Update ui/index.html settings panel:
> - Add "Mémoire & Apprentissage" section with stats grid (10 stat cards)
> - loadMemoryStats() called on settings open
> - Buttons: export fine-tune, voir profil, voir patterns, réinitialiser
> - CSS .stat-card, .stat-val, .stat-label
>
> FILE 5 — Update main.py:
> - Call memory_engine.get_engine().update_active_hours() at startup
> - In _quit_app(): call memory_engine.save_session() and memory_engine.save_current_conversation()
>
> No placeholders. Full implementation.

---

## MISE À JOUR — Mémoire permanente obligatoire

### Règle absolue
Toutes les sessions, conversations et données apprises doivent être sauvegardées en permanence, sans jamais être effacées automatiquement. Aucune limite de sessions ou de conversations.

### Modifications critiques dans memory_engine.py

**1. Supprimer toutes les limites de taille :**
```python
# SUPPRIMER ces lignes — plus jamais de limite :
# if len(self.sessions) > 100:
#     self.sessions = self.sessions[-100:]
# if len(self.conversations) > 200:
#     self.conversations = self.conversations[-200:]
# if len(self.patterns["quality_exchanges"]) > 1000:
#     ...

# REMPLACER par — conservation permanente :
# Toutes les sessions gardées pour toujours
# Toutes les conversations gardées pour toujours  
# Tous les exemples fine-tuning gardés pour toujours
```

**2. Sauvegarde automatique toutes les 60 secondes :**
```python
import threading

def _auto_save_loop(self):
    """Sauvegarde automatique toutes les 60 secondes."""
    while True:
        threading.Event().wait(60)
        try:
            self._save_all()
            logger.debug("Auto-save mémoire effectuée")
        except Exception as e:
            logger.error("Erreur auto-save: %s", e)

def _save_all(self):
    """Sauvegarde complète de toutes les données."""
    save_json(SESSIONS_PATH, self.sessions)
    save_json(CONVERSATIONS_PATH, self.conversations)
    save_json(PROFILE_PATH, self.profile)
    save_json(PATTERNS_PATH, self.patterns)
    logger.info("Mémoire complète sauvegardée — %d sessions, %d convs, %d messages",
        len(self.sessions), len(self.conversations), self.profile["total_messages"])

def start_auto_save(self):
    """Démarre le thread de sauvegarde automatique."""
    t = threading.Thread(target=self._auto_save_loop, daemon=True)
    t.start()
    logger.info("Auto-save mémoire démarré (toutes les 60s)")
```

**3. Sauvegarde sur chaque message (pas seulement à la fin) :**
```python
def add_to_conversation(self, role: str, text: str):
    self.current_conversation["messages"].append({
        "role": role,
        "text": text,
        "time": datetime.now().isoformat()
    })
    if role == "user" and self.current_conversation["title"] == "Nouvelle conversation":
        self.current_conversation["title"] = text[:40] + ("..." if len(text) > 40 else "")
    # Sauvegarde immédiate à chaque message
    self.save_current_conversation()
    # Sauvegarde du profil aussi
    save_json(PROFILE_PATH, self.profile)
```

**4. Sauvegarde sur chaque stat mise à jour :**
```python
def record_message(self, role: str, text: str, intent: str = None, model: str = None):
    # ... existing code ...
    self.profile["total_messages"] += 1
    # Sauvegarde immédiate
    save_json(PROFILE_PATH, self.profile)

def record_app_launch(self, app: str):
    self.current_session["apps_launched"].append(app)
    self.profile["frequent_apps"][app] = self.profile["frequent_apps"].get(app, 0) + 1
    # Sauvegarde immédiate
    save_json(PROFILE_PATH, self.profile)

def update_active_hours(self):
    # ... existing code ...
    # Sauvegarde immédiate
    save_json(PROFILE_PATH, self.profile)
```

**5. Dans __init__, démarrer l'auto-save et restaurer la dernière session :**
```python
def __init__(self):
    # ... existing init code ...
    
    # Démarrer l'auto-save
    self.start_auto_save()
    
    # Log de chargement
    logger.info(
        "Mémoire chargée: %d sessions, %d conversations, %d messages au total",
        len(self.sessions), len(self.conversations), self.profile.get("total_messages", 0)
    )
```

**6. Dans save_session() — ne jamais écraser, toujours appender :**
```python
def save_session(self):
    """Sauvegarde la session courante SANS limite de taille."""
    if not self.current_session.get("messages"):
        return
    self.current_session["end_time"] = datetime.now().isoformat()
    self.current_session["duration_messages"] = len(self.current_session["messages"])
    
    # Chercher si session existe déjà (par ID)
    found = False
    for i, s in enumerate(self.sessions):
        if s.get("date") == self.current_session.get("date"):
            self.sessions[i] = self.current_session
            found = True
            break
    if not found:
        self.sessions.append(dict(self.current_session))
    
    self.profile["total_sessions"] = len(self.sessions)
    self.profile["last_use"] = datetime.now().isoformat()
    if not self.profile.get("first_use"):
        self.profile["first_use"] = datetime.now().isoformat()
    
    # Tout sauvegarder
    self._save_all()
    logger.info("Session sauvegardée. Total: %d sessions", len(self.sessions))
```

**7. Dans main.py — s'assurer que save_session est appelé sur SIGINT, SIGTERM et fermeture normale :**
```python
import atexit
import memory_engine

# Enregistrer la sauvegarde finale pour tous les cas de fermeture
atexit.register(lambda: memory_engine.get_engine().save_session())
atexit.register(lambda: memory_engine.get_engine()._save_all())
```

### Prompt Cursor additionnel

> Apply these critical memory persistence updates to memory_engine.py and main.py:
>
> 1. REMOVE all size limits — sessions, conversations, and quality_exchanges arrays must grow indefinitely, never truncated
> 2. ADD _save_all() method that saves all 4 JSON files atomically
> 3. ADD start_auto_save() that runs _save_all() every 60 seconds in a daemon thread
> 4. MODIFY add_to_conversation() to call save_current_conversation() after every single message
> 5. MODIFY record_message(), record_app_launch(), update_active_hours() to call save_json(PROFILE_PATH, self.profile) after every update
> 6. MODIFY save_session() to never truncate sessions list, always append or update by ID
> 7. MODIFY __init__() to call start_auto_save() and log how much data was loaded
> 8. In main.py, add atexit.register() calls to ensure save_session() and _save_all() are called on any exit (crash, SIGINT, normal close)
>
> The goal: zero data loss. Every message, every session, every learned pattern must survive any shutdown.
> Only modify memory_engine.py and main.py.
