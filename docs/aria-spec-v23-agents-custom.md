# ARIA — Spec v23 : Agents IA personnalisables

## Concept

Un agent est un LLM local (llama.cpp/Ollama) auquel on donne :
- Un **nom** personnalisé (ex: "DevBot", "Coach Maths", "Copilote")
- Une **icône** emoji
- Un **modèle** local choisi parmi ceux installés
- Des **règles** (system prompt personnalisé)
- Des **repos Git** associés (contexte de code)
- Une **couleur** de bulle dans le chat

Les agents s'intègrent directement dans ARIA — on peut switcher d'agent en conversation,
ou en créer un nouveau depuis les paramètres, sans aucune clé API ni connexion internet.

---

## Structure de données — agents dans config.yaml

```yaml
agents:
  default:
    id: "default"
    name: "ARIA"
    icon: "🤖"
    color: "#6C8EFF"
    model: "llama3.1:8b-instruct-q8_0"
    system_prompt: ""   # vide = system prompt global d'ARIA
    rules: []           # règles supplémentaires
    git_repos: []       # chemins locaux vers des repos Git
    created_at: "2026-06-20"

  devbot:
    id: "devbot"
    name: "DevBot"
    icon: "🛠️"
    color: "#4ADE80"
    model: "qwen3:14b"
    system_prompt: "Tu es un expert en développement Python et JavaScript. Réponds toujours avec du code commenté et des explications claires."
    rules:
      - "Toujours proposer des tests unitaires avec le code"
      - "Signaler les problèmes de sécurité potentiels"
      - "Préférer les solutions simples aux over-engineering"
    git_repos:
      - "C:\\Users\\mathi\\OneDrive\\Documents\\assistant-ia\\assistant-vocal"
    created_at: "2026-06-20"
```

---

## Partie 1 — Backend : actions/agents.py

```python
"""
agents.py — Gestion des agents IA personnalisables dans ARIA.
"""
import logging
import yaml
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
import app_paths

logger = logging.getLogger(__name__)

# Agent actif dans la session courante
_active_agent_id: str = "default"


# ── CRUD Agents ───────────────────────────────────────────────────────────────

def _load_agents() -> dict:
    """Charge tous les agents depuis config.yaml."""
    try:
        with app_paths.config_path().open('r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        agents = cfg.get('agents', {})
        # S'assurer que l'agent default existe toujours
        if 'default' not in agents:
            agents['default'] = _default_agent()
        return agents
    except Exception as e:
        logger.error("Erreur chargement agents: %s", e)
        return {'default': _default_agent()}


def _save_agents(agents: dict) -> None:
    """Sauvegarde les agents dans config.yaml."""
    try:
        cfg_path = app_paths.config_path()
        with cfg_path.open('r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        cfg['agents'] = agents
        with cfg_path.open('w', encoding='utf-8') as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        logger.error("Erreur sauvegarde agents: %s", e)
        raise


def _default_agent() -> dict:
    return {
        'id': 'default',
        'name': 'ARIA',
        'icon': '🤖',
        'color': '#6C8EFF',
        'model': 'llama3.1:8b-instruct-q8_0',
        'system_prompt': '',
        'rules': [],
        'git_repos': [],
        'created_at': datetime.now().strftime('%Y-%m-%d'),
    }


def get_all_agents() -> list[dict]:
    """Retourne la liste de tous les agents."""
    agents = _load_agents()
    return list(agents.values())


def get_agent(agent_id: str) -> dict | None:
    """Retourne un agent par son ID."""
    agents = _load_agents()
    return agents.get(agent_id)


def create_agent(
    name: str,
    icon: str = '🤖',
    color: str = '#6C8EFF',
    model: str = None,
    system_prompt: str = '',
    rules: list[str] = None,
    git_repos: list[str] = None,
) -> dict:
    """Crée un nouvel agent."""
    from llm import MODELS
    agents = _load_agents()

    # Générer un ID unique basé sur le nom
    base_id = name.lower().replace(' ', '_')[:20]
    agent_id = base_id
    counter = 1
    while agent_id in agents:
        agent_id = f"{base_id}_{counter}"
        counter += 1

    agent = {
        'id': agent_id,
        'name': name,
        'icon': icon,
        'color': color,
        'model': model or MODELS.get('fast', 'llama3.1:8b-instruct-q8_0'),
        'system_prompt': system_prompt,
        'rules': rules or [],
        'git_repos': git_repos or [],
        'created_at': datetime.now().strftime('%Y-%m-%d'),
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

    # L'agent default ne peut pas changer d'ID
    if agent_id == 'default' and 'id' in kwargs:
        del kwargs['id']

    agents[agent_id].update(kwargs)
    _save_agents(agents)
    logger.info("Agent mis à jour: %s", agent_id)
    return agents[agent_id]


def delete_agent(agent_id: str) -> bool:
    """Supprime un agent (sauf default)."""
    if agent_id == 'default':
        raise ValueError("L'agent par défaut ne peut pas être supprimé")

    agents = _load_agents()
    if agent_id not in agents:
        return False

    del agents[agent_id]
    _save_agents(agents)

    # Si c'était l'agent actif, revenir au default
    global _active_agent_id
    if _active_agent_id == agent_id:
        _active_agent_id = 'default'

    logger.info("Agent supprimé: %s", agent_id)
    return True


# ── Agent actif ────────────────────────────────────────────────────────────────

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
    logger.info("Agent actif: %s (%s)", agent['name'], agent_id)
    return agent


# ── Contexte Git ───────────────────────────────────────────────────────────────

def get_git_context(agent: dict, max_files: int = 10) -> str:
    """
    Génère un résumé du contexte Git pour un agent.
    Liste les fichiers récemment modifiés dans chaque repo.
    """
    if not agent.get('git_repos'):
        return ""

    import subprocess
    context_parts = []

    for repo_path in agent['git_repos']:
        repo = Path(repo_path)
        if not repo.exists() or not (repo / '.git').exists():
            logger.debug("Repo non trouvé ou pas un repo Git: %s", repo_path)
            continue

        try:
            # Fichiers récemment modifiés (dernière semaine)
            result = subprocess.run(
                ['git', 'log', '--name-only', '--pretty=format:', '--since=1 week ago'],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
            unique_files = list(dict.fromkeys(files))[:max_files]

            # Dernier commit
            last_commit = subprocess.run(
                ['git', 'log', '-1', '--pretty=format:%h %s (%ar)'],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            repo_name = repo.name
            context_parts.append(
                f"Repo '{repo_name}' ({repo_path}):\n"
                f"  Dernier commit: {last_commit.stdout.strip()}\n"
                f"  Fichiers récents: {', '.join(unique_files[:5]) if unique_files else 'aucun'}"
            )
        except Exception as e:
            logger.debug("Erreur git context %s: %s", repo_path, e)

    return "\n\n".join(context_parts)


def build_system_prompt(agent: dict, base_prompt: str = "") -> str:
    """
    Construit le system prompt complet pour un agent.
    Combine : base ARIA + custom agent + règles + contexte Git.
    """
    parts = []

    # System prompt de base ARIA
    if base_prompt:
        parts.append(base_prompt)

    # System prompt personnalisé de l'agent
    if agent.get('system_prompt'):
        parts.append(agent['system_prompt'])

    # Règles supplémentaires
    if agent.get('rules'):
        rules_text = "Règles à suivre impérativement :\n" + \
                     "\n".join(f"- {r}" for r in agent['rules'])
        parts.append(rules_text)

    # Contexte Git
    git_ctx = get_git_context(agent)
    if git_ctx:
        parts.append(f"Contexte des projets en cours :\n{git_ctx}")

    # Identité de l'agent
    if agent.get('name') and agent['name'] != 'ARIA':
        parts.append(f"Tu t'appelles {agent['name']}. Sois cohérent avec ce nom.")

    return "\n\n".join(p for p in parts if p)
```

---

## Partie 2 — ui.py : fonctions exposées

```python
# Dans ui.py, ajouter :

def get_agents(self) -> str:
    import json
    from actions import agents as _agents
    try:
        return json.dumps(_agents.get_all_agents())
    except Exception as e:
        return json.dumps([])

def create_agent(self, data_json: str) -> str:
    import json
    from actions import agents as _agents
    try:
        data = json.loads(data_json)
        agent = _agents.create_agent(
            name=data.get('name', 'Nouvel agent'),
            icon=data.get('icon', '🤖'),
            color=data.get('color', '#6C8EFF'),
            model=data.get('model'),
            system_prompt=data.get('system_prompt', ''),
            rules=data.get('rules', []),
            git_repos=data.get('git_repos', []),
        )
        return json.dumps({'success': True, 'agent': agent})
    except Exception as e:
        return json.dumps({'success': False, 'error': str(e)})

def update_agent(self, agent_id: str, data_json: str) -> str:
    import json
    from actions import agents as _agents
    try:
        data = json.loads(data_json)
        agent = _agents.update_agent(agent_id, **data)
        return json.dumps({'success': True, 'agent': agent})
    except Exception as e:
        return json.dumps({'success': False, 'error': str(e)})

def delete_agent(self, agent_id: str) -> str:
    import json
    from actions import agents as _agents
    try:
        success = _agents.delete_agent(agent_id)
        return json.dumps({'success': success})
    except Exception as e:
        return json.dumps({'success': False, 'error': str(e)})

def set_active_agent(self, agent_id: str) -> str:
    import json
    from actions import agents as _agents
    try:
        agent = _agents.set_active_agent(agent_id)
        return json.dumps({'success': True, 'agent': agent})
    except Exception as e:
        return json.dumps({'success': False, 'error': str(e)})

def get_active_agent(self) -> str:
    import json
    from actions import agents as _agents
    return json.dumps(_agents.get_active_agent())

def validate_git_repo(self, path: str) -> str:
    import json
    from pathlib import Path
    p = Path(path)
    valid = p.exists() and (p / '.git').exists()
    return json.dumps({'valid': valid, 'path': str(p.resolve()) if valid else None})
```

---

## Partie 3 — llm.py : utiliser l'agent actif

```python
# Dans llm.py, modifier ask() pour utiliser le system prompt de l'agent actif

def ask(text: str, conv_mode: str = 'ecrit', on_token=None) -> str:
    from actions import agents as _agents
    import memory_engine as _me

    # Récupérer l'agent actif
    active_agent = _agents.get_active_agent()
    agent_model = active_agent.get('model') or MODELS['fast']

    # Construire le system prompt avec le contexte de l'agent
    base_system = _me.build_personalized_system_prompt()
    agent_system = _agents.build_system_prompt(active_agent, base_system)

    # Mode vocal : réponses courtes
    if conv_mode == 'vocal':
        agent_system += "\nMode vocal: réponds en 1-3 phrases max, pas de markdown."

    # ... reste du routing inchangé, mais utiliser agent_model et agent_system
    result = generate(
        prompt,
        model=agent_model,
        system=agent_system,
        stream=True,
        max_tokens=150 if conv_mode == 'vocal' else 500,
        on_token=on_token,
    )
    return result
```

---

## Partie 4 — UI : section Agents dans les paramètres

### Vue liste des agents (dans l'accordéon "Agents IA")

```html
<!-- Dans settings-panel, nouvelle section accordéon -->
<div class="settings-accordion" id="acc-agents">
  <div class="acc-header" onclick="app.toggleAccordion('agents')">
    🧠 Agents IA <span class="acc-chevron">▸</span>
    <span id="agents-count-badge" class="agent-count-badge">1</span>
  </div>
  <div class="acc-body hidden" id="acc-agents-body">

    <!-- Liste des agents -->
    <div id="agents-list"></div>

    <!-- Bouton créer -->
    <button class="agent-create-btn" onclick="app.openAgentEditor(null)">
      + Créer un agent
    </button>
  </div>
</div>
```

### Modal éditeur d'agent

```html
<!-- Modal plein écran pour créer/éditer un agent -->
<div id="agent-editor-modal" class="modal-overlay hidden">
  <div class="agent-editor-card">

    <!-- Header -->
    <div class="agent-editor-header">
      <div class="agent-preview" id="agent-preview">
        <span id="agent-preview-icon">🤖</span>
        <span id="agent-preview-name">Nouvel agent</span>
      </div>
      <button onclick="app.closeAgentEditor()">✕</button>
    </div>

    <div class="agent-editor-body">

      <!-- Colonne 1 : Identité -->
      <div class="agent-editor-section">
        <div class="agent-section-title">Identité</div>

        <!-- Emoji + Nom sur une ligne -->
        <div style="display:flex;gap:8px;align-items:flex-end;margin-bottom:12px">
          <div>
            <label class="agent-label">Icône</label>
            <div class="emoji-picker-wrapper">
              <button class="emoji-btn" id="agent-icon-btn" onclick="app.toggleAgentEmojiPicker()">🤖</button>
              <div class="emoji-picker" id="agent-emoji-picker" style="display:none">
                <!-- Grille d'emojis générée dynamiquement -->
              </div>
            </div>
          </div>
          <div style="flex:1">
            <label class="agent-label">Nom de l'agent</label>
            <input type="text" id="agent-name-input" placeholder="DevBot, Coach Maths, Copilote..."
              maxlength="30"
              oninput="app.updateAgentPreview()"
              class="agent-input">
          </div>
          <div style="width:100px">
            <label class="agent-label">Couleur</label>
            <div class="color-swatches" id="agent-color-swatches">
              <!-- Pastilles de couleur -->
            </div>
          </div>
        </div>

        <!-- Modèle -->
        <div style="margin-bottom:12px">
          <label class="agent-label">Modèle IA local</label>
          <select id="agent-model-select" class="agent-select">
            <!-- Rempli dynamiquement avec les modèles disponibles -->
          </select>
          <div style="font-size:10px;color:var(--text3);margin-top:4px">
            100% local — aucune donnée envoyée en ligne
          </div>
        </div>
      </div>

      <!-- Colonne 2 : Comportement -->
      <div class="agent-editor-section">
        <div class="agent-section-title">Comportement</div>

        <!-- System prompt -->
        <div style="margin-bottom:12px">
          <label class="agent-label">Instructions personnalisées</label>
          <textarea id="agent-system-prompt"
            placeholder="Ex: Tu es un expert en mathématiques. Explique toujours avec des exemples concrets."
            rows="4"
            class="agent-textarea"></textarea>
        </div>

        <!-- Règles -->
        <div style="margin-bottom:12px">
          <label class="agent-label">Règles supplémentaires</label>
          <div id="agent-rules-list"></div>
          <div style="display:flex;gap:6px;margin-top:6px">
            <input type="text" id="agent-rule-input"
              placeholder="Ex: Toujours proposer des alternatives"
              class="agent-input" style="flex:1"
              onkeydown="if(event.key==='Enter') app.addAgentRule()">
            <button class="agent-add-btn" onclick="app.addAgentRule()">+</button>
          </div>
        </div>
      </div>

      <!-- Colonne 3 : Contexte Git -->
      <div class="agent-editor-section">
        <div class="agent-section-title">Contexte de code (Git)</div>
        <div style="font-size:11px;color:var(--text3);margin-bottom:10px">
          L'agent accédera aux fichiers récemment modifiés dans ces repos
          pour mieux comprendre ton code.
        </div>

        <div id="agent-repos-list"></div>

        <div style="display:flex;gap:6px;margin-top:6px">
          <input type="text" id="agent-repo-input"
            placeholder="C:\Users\mathi\projets\mon-repo"
            class="agent-input" style="flex:1"
            onkeydown="if(event.key==='Enter') app.addAgentRepo()">
          <button class="agent-add-btn" onclick="app.addAgentRepo()" title="Ajouter">+</button>
        </div>

        <!-- Indicateur de validité du repo -->
        <div id="agent-repo-status" style="font-size:10px;margin-top:4px;height:14px"></div>

        <!-- Stats du repo sélectionné -->
        <div id="agent-repo-stats" style="margin-top:8px"></div>
      </div>

    </div>

    <!-- Footer -->
    <div class="agent-editor-footer">
      <button class="agent-delete-btn" id="agent-delete-btn" onclick="app.deleteCurrentAgent()" style="display:none">
        🗑️ Supprimer
      </button>
      <div style="flex:1"></div>
      <button class="agent-cancel-btn" onclick="app.closeAgentEditor()">Annuler</button>
      <button class="agent-save-btn" onclick="app.saveAgent()">✓ Enregistrer</button>
    </div>

  </div>
</div>
```

### Sélecteur d'agent rapide dans le header du chat

```html
<!-- Dans #header, à gauche du titre de conversation -->
<div id="agent-selector" onclick="app.toggleAgentDropdown()">
  <span id="active-agent-icon">🤖</span>
  <span id="active-agent-name">ARIA</span>
  <span style="font-size:10px;opacity:0.5">▾</span>
</div>

<div id="agent-dropdown" class="hidden">
  <!-- Liste des agents à sélectionner, générée dynamiquement -->
</div>
```

---

## Partie 5 — JS complet pour la gestion des agents

```javascript
// ── État de l'éditeur ─────────────────────────────────────────────────────────
_editingAgentId: null,
_agentRules: [],
_agentRepos: [],

// ── Couleurs disponibles ──────────────────────────────────────────────────────
AGENT_COLORS: [
  '#6C8EFF', '#4ADE80', '#F59E0B', '#F87171',
  '#A78BFA', '#34D399', '#FB923C', '#60A5FA',
  '#E879F9', '#2DD4BF', '#FBBF24', '#94A3B8',
],

AGENT_EMOJIS: [
  '🤖','🛠️','📚','🎯','🚀','💡','🔬','🎨',
  '🏆','⚡','🔥','❄️','🌊','🎸','🎧','📷',
  '✈️','🚁','🏎️','⚽','🎮','🎲','♟️','🃏',
  '👨‍💻','👩‍💻','🧑‍🔬','🧑‍🎨','👨‍✈️','🦁','🐉','🦊',
],

// ── Initialisation ────────────────────────────────────────────────────────────
async loadAgents() {
  try {
    const raw = await this.api('get_agents');
    const agents = JSON.parse(raw || '[]');
    this.renderAgentsList(agents);
    this.renderAgentDropdown(agents);
    this.updateAgentCountBadge(agents.length);
  } catch(e) {
    console.error('loadAgents error:', e);
  }
},

// ── Liste des agents dans les paramètres ──────────────────────────────────────
renderAgentsList(agents) {
  const list = document.getElementById('agents-list');
  if (!list) return;

  list.innerHTML = agents.map(agent => `
    <div class="agent-item" style="border-left:3px solid ${agent.color || '#6C8EFF'}">
      <div class="agent-item-info">
        <span class="agent-item-icon">${agent.icon || '🤖'}</span>
        <div>
          <div class="agent-item-name">${this.esc(agent.name)}</div>
          <div class="agent-item-model">${agent.model || 'Modèle par défaut'}</div>
        </div>
      </div>
      <div class="agent-item-actions">
        ${agent.id !== 'default' ? `
          <button onclick="app.setActiveAgent('${agent.id}')" class="agent-use-btn">
            Utiliser
          </button>
        ` : '<span style="font-size:10px;color:var(--accent)">Actif</span>'}
        <button onclick="app.openAgentEditor('${agent.id}')" class="agent-edit-btn">✏️</button>
      </div>
    </div>
  `).join('');
},

// ── Dropdown rapide dans le header ────────────────────────────────────────────
renderAgentDropdown(agents) {
  const dropdown = document.getElementById('agent-dropdown');
  if (!dropdown) return;

  dropdown.innerHTML = agents.map(agent => `
    <div class="agent-dropdown-item" onclick="app.setActiveAgent('${agent.id}')">
      <span style="font-size:18px">${agent.icon || '🤖'}</span>
      <div>
        <div style="font-size:13px;color:var(--text)">${this.esc(agent.name)}</div>
        <div style="font-size:10px;color:var(--text3)">${agent.model || ''}</div>
      </div>
    </div>
  `).join('') + `
    <div class="agent-dropdown-divider"></div>
    <div class="agent-dropdown-item" onclick="app.openAgentEditor(null);app.closeAgentDropdown()">
      <span>+</span>
      <div style="font-size:13px;color:var(--accent)">Créer un agent</div>
    </div>
  `;
},

toggleAgentDropdown() {
  const dd = document.getElementById('agent-dropdown');
  dd?.classList.toggle('hidden');
},

closeAgentDropdown() {
  document.getElementById('agent-dropdown')?.classList.add('hidden');
},

async setActiveAgent(agentId) {
  const raw = await this.api('set_active_agent', agentId);
  const result = JSON.parse(raw || '{}');
  if (result.success) {
    const agent = result.agent;
    document.getElementById('active-agent-icon').textContent = agent.icon || '🤖';
    document.getElementById('active-agent-name').textContent = agent.name;
    document.getElementById('agent-selector').style.borderColor = agent.color || '#6C8EFF';
    this.closeAgentDropdown();
    this.showToast(`Agent "${agent.icon} ${agent.name}" activé`, 'success');
  }
},

// ── Éditeur d'agent ───────────────────────────────────────────────────────────
async openAgentEditor(agentId) {
  this._editingAgentId = agentId;
  this._agentRules = [];
  this._agentRepos = [];

  // Charger les modèles disponibles
  const modelsRaw = await this.api('get_available_models');
  const modelsData = JSON.parse(modelsRaw || '{}');
  const models = modelsData.local_models || [];

  // Remplir le select modèle
  const modelSelect = document.getElementById('agent-model-select');
  if (modelSelect) {
    modelSelect.innerHTML = models.map(m =>
      `<option value="${m}">${m}</option>`
    ).join('');
  }

  // Remplir le picker d'emojis
  const picker = document.getElementById('agent-emoji-picker');
  if (picker) {
    picker.innerHTML = this.AGENT_EMOJIS.map(e =>
      `<button class="emoji-option" onclick="app.selectAgentEmoji('${e}')">${e}</button>`
    ).join('');
  }

  // Remplir les pastilles de couleur
  const colorSwatches = document.getElementById('agent-color-swatches');
  if (colorSwatches) {
    colorSwatches.innerHTML = this.AGENT_COLORS.map(c => `
      <button class="color-swatch" style="background:${c}"
        onclick="app.selectAgentColor('${c}')"
        title="${c}">
      </button>
    `).join('');
  }

  if (agentId) {
    // Mode édition — charger les données de l'agent
    const raw = await this.api('get_agents');
    const agents = JSON.parse(raw || '[]');
    const agent = agents.find(a => a.id === agentId);
    if (agent) {
      document.getElementById('agent-name-input').value = agent.name;
      document.getElementById('agent-icon-btn').textContent = agent.icon || '🤖';
      document.getElementById('agent-system-prompt').value = agent.system_prompt || '';
      if (modelSelect) modelSelect.value = agent.model || models[0];
      this._agentRules = [...(agent.rules || [])];
      this._agentRepos = [...(agent.git_repos || [])];
      this._selectedColor = agent.color || '#6C8EFF';

      // Montrer le bouton supprimer (sauf pour default)
      const deleteBtn = document.getElementById('agent-delete-btn');
      if (deleteBtn) deleteBtn.style.display = agentId === 'default' ? 'none' : 'flex';
    }
  } else {
    // Mode création — valeurs par défaut
    document.getElementById('agent-name-input').value = '';
    document.getElementById('agent-icon-btn').textContent = '🤖';
    document.getElementById('agent-system-prompt').value = '';
    this._selectedColor = '#6C8EFF';
    document.getElementById('agent-delete-btn').style.display = 'none';
  }

  this.renderAgentRulesList();
  this.renderAgentReposList();
  this.updateAgentPreview();

  // Ouvrir le modal avec animation
  const modal = document.getElementById('agent-editor-modal');
  modal?.classList.remove('hidden');
  requestAnimationFrame(() => modal?.classList.add('modal-open'));
},

closeAgentEditor() {
  const modal = document.getElementById('agent-editor-modal');
  modal?.classList.remove('modal-open');
  setTimeout(() => modal?.classList.add('hidden'), 250);
},

updateAgentPreview() {
  const name = document.getElementById('agent-name-input')?.value || 'Nouvel agent';
  const icon = document.getElementById('agent-icon-btn')?.textContent || '🤖';
  document.getElementById('agent-preview-name').textContent = name;
  document.getElementById('agent-preview-icon').textContent = icon;
},

selectAgentEmoji(emoji) {
  document.getElementById('agent-icon-btn').textContent = emoji;
  document.getElementById('agent-emoji-picker').style.display = 'none';
  this.updateAgentPreview();
},

selectAgentColor(color) {
  this._selectedColor = color;
  document.querySelectorAll('.color-swatch').forEach(s => {
    s.classList.toggle('active', s.style.background === color);
  });
},

// ── Règles ────────────────────────────────────────────────────────────────────
addAgentRule() {
  const input = document.getElementById('agent-rule-input');
  const rule = input?.value?.trim();
  if (!rule) return;
  this._agentRules.push(rule);
  input.value = '';
  this.renderAgentRulesList();
},

removeAgentRule(idx) {
  this._agentRules.splice(idx, 1);
  this.renderAgentRulesList();
},

renderAgentRulesList() {
  const list = document.getElementById('agent-rules-list');
  if (!list) return;
  list.innerHTML = this._agentRules.map((rule, i) => `
    <div class="agent-tag-item">
      <span>${this.esc(rule)}</span>
      <button onclick="app.removeAgentRule(${i})">✕</button>
    </div>
  `).join('');
},

// ── Repos Git ─────────────────────────────────────────────────────────────────
async addAgentRepo() {
  const input = document.getElementById('agent-repo-input');
  const path = input?.value?.trim();
  if (!path) return;

  // Valider le chemin
  const statusEl = document.getElementById('agent-repo-status');
  statusEl.textContent = 'Vérification...';
  statusEl.style.color = 'var(--text3)';

  const raw = await this.api('validate_git_repo', path);
  const result = JSON.parse(raw || '{}');

  if (result.valid) {
    this._agentRepos.push(result.path);
    input.value = '';
    statusEl.textContent = '✅ Repo Git valide';
    statusEl.style.color = 'var(--success)';
    this.renderAgentReposList();
    setTimeout(() => statusEl.textContent = '', 2000);
  } else {
    statusEl.textContent = '❌ Chemin invalide ou pas un repo Git';
    statusEl.style.color = 'var(--error)';
  }
},

removeAgentRepo(idx) {
  this._agentRepos.splice(idx, 1);
  this.renderAgentReposList();
},

renderAgentReposList() {
  const list = document.getElementById('agent-repos-list');
  if (!list) return;
  list.innerHTML = this._agentRepos.map((repo, i) => `
    <div class="agent-tag-item agent-repo-item">
      <span style="font-size:11px">📁 ${this.esc(repo)}</span>
      <button onclick="app.removeAgentRepo(${i})">✕</button>
    </div>
  `).join('');
},

// ── Sauvegarde ────────────────────────────────────────────────────────────────
async saveAgent() {
  const name = document.getElementById('agent-name-input')?.value?.trim();
  if (!name) {
    this.showToast('Le nom est obligatoire', 'error');
    return;
  }

  const data = {
    name,
    icon: document.getElementById('agent-icon-btn')?.textContent || '🤖',
    color: this._selectedColor || '#6C8EFF',
    model: document.getElementById('agent-model-select')?.value,
    system_prompt: document.getElementById('agent-system-prompt')?.value || '',
    rules: this._agentRules,
    git_repos: this._agentRepos,
  };

  let raw;
  if (this._editingAgentId) {
    raw = await this.api('update_agent', this._editingAgentId, JSON.stringify(data));
  } else {
    raw = await this.api('create_agent', JSON.stringify(data));
  }

  const result = JSON.parse(raw || '{}');
  if (result.success) {
    this.showToast(`Agent "${data.icon} ${data.name}" sauvegardé ✓`, 'success');
    this.closeAgentEditor();
    await this.loadAgents();
  } else {
    this.showToast('Erreur: ' + (result.error || 'inconnue'), 'error');
  }
},

async deleteCurrentAgent() {
  if (!this._editingAgentId || this._editingAgentId === 'default') return;
  if (!confirm('Supprimer cet agent ? Cette action est irréversible.')) return;

  const raw = await this.api('delete_agent', this._editingAgentId);
  const result = JSON.parse(raw || '{}');
  if (result.success) {
    this.showToast('Agent supprimé', 'success');
    this.closeAgentEditor();
    await this.loadAgents();
  }
},

updateAgentCountBadge(count) {
  const badge = document.getElementById('agents-count-badge');
  if (badge) badge.textContent = count;
},
```

---

## Partie 6 — CSS

```css
/* ── Agent selector dans le header ──────────────────────────────────────── */
#agent-selector {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(108,142,255,0.2);
  border-radius: 20px;
  cursor: pointer;
  font-size: 13px;
  transition: background 0.15s, border-color 0.2s;
  user-select: none;
}

#agent-selector:hover { background: rgba(255,255,255,0.09); }

#agent-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 500;
  background: rgba(20,20,30,0.85);
  backdrop-filter: blur(30px) saturate(180%);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 6px;
  min-width: 220px;
  box-shadow: 0 12px 40px rgba(0,0,0,0.35);
  animation: dropIn 0.2s cubic-bezier(0.34,1.4,0.64,1);
}

@keyframes dropIn {
  from { opacity:0; transform:translateY(-8px) scale(0.97); }
  to   { opacity:1; transform:translateY(0) scale(1); }
}

.agent-dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.1s;
}

.agent-dropdown-item:hover { background: rgba(255,255,255,0.07); }

.agent-dropdown-divider {
  height: 1px;
  background: rgba(255,255,255,0.07);
  margin: 4px 0;
}

/* ── Liste agents dans paramètres ────────────────────────────────────────── */
.agent-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: rgba(255,255,255,0.03);
  border-radius: 10px;
  margin-bottom: 6px;
  border-left-width: 3px;
  border-left-style: solid;
}

.agent-item-info { display: flex; align-items: center; gap: 8px; }
.agent-item-icon { font-size: 20px; }
.agent-item-name { font-size: 13px; color: var(--text); font-weight: 500; }
.agent-item-model { font-size: 10px; color: var(--text3); }
.agent-item-actions { display: flex; gap: 6px; align-items: center; }

.agent-use-btn {
  padding: 4px 10px;
  background: rgba(108,142,255,0.12);
  border: 1px solid rgba(108,142,255,0.25);
  border-radius: 6px;
  color: var(--accent);
  font-size: 11px;
  cursor: pointer;
  font-family: inherit;
}

.agent-edit-btn {
  width: 28px; height: 28px;
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  display: flex; align-items: center; justify-content: center;
}

.agent-count-badge {
  background: rgba(108,142,255,0.2);
  color: var(--accent);
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
  margin-left: auto;
}

.agent-create-btn {
  width: 100%;
  padding: 10px;
  background: rgba(108,142,255,0.08);
  border: 1px dashed rgba(108,142,255,0.3);
  border-radius: 10px;
  color: var(--accent);
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
  margin-top: 8px;
  transition: background 0.15s;
}

.agent-create-btn:hover { background: rgba(108,142,255,0.15); }

/* ── Modal éditeur d'agent ───────────────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.5);
  backdrop-filter: blur(8px);
  z-index: 9000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.agent-editor-card {
  background: rgba(16,16,26,0.92);
  backdrop-filter: blur(40px) saturate(180%);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 22px;
  width: min(860px, 95vw);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 24px 64px rgba(0,0,0,0.5);
  opacity: 0;
  transform: scale(0.96) translateY(12px);
  transition: opacity 0.25s, transform 0.25s cubic-bezier(0.34,1.2,0.64,1);
}

.modal-open .agent-editor-card,
.agent-editor-card { /* when modal-open is on the overlay */
  opacity: 1;
  transform: scale(1) translateY(0);
}

/* Trick: apply transition on the card when overlay gets .modal-open */
#agent-editor-modal.modal-open .agent-editor-card {
  opacity: 1;
  transform: scale(1) translateY(0);
}

.agent-editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-bottom: 1px solid rgba(255,255,255,0.07);
}

.agent-preview {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}

#agent-preview-icon { font-size: 26px; }

.agent-editor-body {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0;
  overflow-y: auto;
  flex: 1;
}

.agent-editor-section {
  padding: 18px 20px;
  border-right: 1px solid rgba(255,255,255,0.06);
}

.agent-editor-section:last-child { border-right: none; }

.agent-section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.8px;
  margin-bottom: 14px;
}

.agent-label {
  display: block;
  font-size: 11px;
  color: var(--text3);
  margin-bottom: 5px;
}

.agent-input {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 8px 10px;
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
  outline: none;
  width: 100%;
  transition: border-color 0.15s;
}

.agent-input:focus { border-color: rgba(108,142,255,0.4); }

.agent-select {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 8px 10px;
  color: var(--text);
  font-family: inherit;
  font-size: 12px;
  width: 100%;
  cursor: pointer;
  outline: none;
}

.agent-textarea {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--text);
  font-family: inherit;
  font-size: 12px;
  line-height: 1.6;
  resize: vertical;
  width: 100%;
  outline: none;
  transition: border-color 0.15s;
}

.agent-textarea:focus { border-color: rgba(108,142,255,0.4); }

.agent-tag-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  background: rgba(255,255,255,0.04);
  border-radius: 6px;
  margin-bottom: 4px;
  font-size: 11px;
  color: var(--text2);
  gap: 6px;
}

.agent-tag-item button {
  background: none; border: none; color: var(--text3);
  cursor: pointer; font-size: 10px; flex-shrink: 0;
  padding: 2px 4px; border-radius: 4px;
}

.agent-tag-item button:hover { background: rgba(239,68,68,0.15); color: var(--error); }

.agent-repo-item { border-left: 2px solid rgba(74,222,128,0.3); padding-left: 8px; }

.agent-add-btn {
  width: 36px; height: 36px;
  background: rgba(108,142,255,0.12);
  border: 1px solid rgba(108,142,255,0.25);
  border-radius: 8px;
  color: var(--accent);
  font-size: 18px;
  cursor: pointer;
  flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
}

/* Pastilles couleur */
.color-swatches {
  display: flex; flex-wrap: wrap; gap: 4px;
}

.color-swatch {
  width: 20px; height: 20px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  transition: transform 0.15s, border-color 0.15s;
}

.color-swatch:hover { transform: scale(1.2); }
.color-swatch.active { border-color: white; transform: scale(1.1); }

/* Footer */
.agent-editor-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 22px;
  border-top: 1px solid rgba(255,255,255,0.07);
}

.agent-save-btn {
  padding: 10px 24px;
  background: var(--accent);
  border: none;
  border-radius: 10px;
  color: white;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s, transform 0.1s;
}

.agent-save-btn:hover { opacity: 0.9; transform: translateY(-1px); }

.agent-cancel-btn {
  padding: 10px 18px;
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text2);
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
}

.agent-delete-btn {
  padding: 8px 14px;
  background: rgba(239,68,68,0.1);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: 10px;
  color: var(--error);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
  display: flex; align-items: center; gap: 5px;
}
```

---

## Prompt Cursor

> Implémenter le système d'agents IA personnalisables dans ARIA.
>
> **FICHIER 1 — Créer actions/agents.py** avec le contenu complet :
> `_load_agents()`, `_save_agents()`, `_default_agent()`, `get_all_agents()`,
> `get_agent(id)`, `create_agent(...)`, `update_agent(id, **kwargs)`,
> `delete_agent(id)`, `get_active_agent()`, `set_active_agent(id)`,
> `get_git_context(agent)`, `build_system_prompt(agent, base_prompt)`.
>
> **FICHIER 2 — ui.py** : ajouter `get_agents()`, `create_agent(data_json)`,
> `update_agent(agent_id, data_json)`, `delete_agent(agent_id)`,
> `set_active_agent(agent_id)`, `get_active_agent()`, `validate_git_repo(path)`.
>
> **FICHIER 3 — llm.py** : dans `ask()`, récupérer l'agent actif via
> `agents.get_active_agent()`, utiliser `agent['model']` comme modèle et
> `agents.build_system_prompt(agent, base_system)` comme system prompt.
>
> **FICHIER 4 — config.yaml** : ajouter la section `agents` avec l'agent
> `default` comme spécifié.
>
> **FICHIER 5 — ui/index.html** :
>
> - Ajouter la section accordéon "🧠 Agents IA" dans les paramètres avec
>   la liste des agents et le bouton "Créer un agent"
> - Ajouter le modal `#agent-editor-modal` avec les 3 colonnes (Identité,
>   Comportement, Git) et le footer (Supprimer, Annuler, Enregistrer)
> - Ajouter le sélecteur d'agent `#agent-selector` dans le header du chat
>   avec le dropdown `#agent-dropdown`
> - Ajouter tout le JS : `loadAgents()`, `renderAgentsList()`,
>   `renderAgentDropdown()`, `toggleAgentDropdown()`, `setActiveAgent()`,
>   `openAgentEditor()`, `closeAgentEditor()`, `updateAgentPreview()`,
>   `selectAgentEmoji()`, `selectAgentColor()`, `addAgentRule()`,
>   `removeAgentRule()`, `renderAgentRulesList()`, `addAgentRepo()`,
>   `removeAgentRepo()`, `renderAgentReposList()`, `saveAgent()`,
>   `deleteCurrentAgent()`, `updateAgentCountBadge()`
> - Appeler `loadAgents()` dans `init()` et fermer le dropdown au clic
>   en dehors via un listener global `document.addEventListener('click', ...)`
> - Ajouter tout le CSS spécifié (agent-selector, dropdown, modal, etc.)
>
> Créer : actions/agents.py
> Modifier : ui.py, llm.py, config.yaml, ui/index.html
