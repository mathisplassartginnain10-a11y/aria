# Voix IA — Whisper local pour ARIA

Ce dossier contient une copie du dépôt [openai/whisper](https://github.com/openai/whisper) (`whisper-main/`).

ARIA l'utilise automatiquement comme **backend STT de secours** si `faster-whisper` échoue, ou en mode explicite.

## Structure attendue

```
voix ia/
  whisper-main/
    whisper/
      __init__.py
      ...
```

## Configuration (`config.yaml`)

```yaml
stt:
  backend: auto          # auto | faster_whisper | openai_whisper
  model: small
  language: fr
```

| Backend | Description |
|---------|-------------|
| `auto` | faster-whisper si disponible, sinon voix ia |
| `faster_whisper` | CTranslate2 (défaut, rapide) |
| `openai_whisper` | Whisper PyTorch local (voix ia/) |

## Dépendances

```bash
pip install torch tiktoken
```

Les poids `.pt` sont téléchargés dans `data/whisper_models/` (hors git).

## Vérifier l'installation

```bash
.\.venv\Scripts\python.exe -c "import stt_whisper_local; print(stt_whisper_local.is_available())"
.\.venv\Scripts\python.exe scripts\test_whisper_fr.py
```

Diagnostic depuis l'UI : Paramètres → Diagnostic micro / STT.
