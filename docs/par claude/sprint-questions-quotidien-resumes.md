# Sprint — Questions du quotidien + Résumés de recherche

## Objectif
ARIA doit répondre naturellement aux questions courantes du quotidien,
et quand une recherche web est faite, présenter un résumé clair et structuré
plutôt qu'un mur de texte brut.

---

## Partie 1 — Questions du quotidien (sans recherche web)

### Ce que Cursor doit implémenter dans llm.py

Ajouter une détection rapide (regex, 0ms) pour toutes les questions
courantes qui n'ont pas besoin d'internet. Ces réponses doivent être
immédiates, naturelles, en français, et adaptées à Mathis.

**Catégories à gérer directement :**

**Heure et date**
"quelle heure est-il", "on est quel jour", "quelle date", "quel mois",
"quelle année" → répondre avec `datetime.now()` formaté en français

**Météo locale**
"quel temps fait-il", "météo", "il fait chaud", "va-t-il pleuvoir" →
appeler `get_weather_widget()` qui utilise wttr.in pour Couëron,
puis formuler une réponse naturelle en une phrase

**Batterie et système**
"batterie", "charge", "combien de RAM", "utilisation CPU" →
utiliser `psutil` pour lire les vraies valeurs et répondre directement

**Calculs simples**
"combien fait X fois Y", "calcule", "combien ça fait" →
utiliser `eval()` sécurisé ou la lib `math` pour répondre instantanément

**Définitions et explications simples**
"c'est quoi", "qu'est-ce que", "définition de", "explique moi" →
chercher d'abord dans Wikipedia (une seule requête rapide),
si le résumé Wikipedia est bon (> 100 chars) l'utiliser directement
sans passer par le LLM heavy

**Conversion d'unités**
"convertis X en Y", "combien de km en miles", "celsius en fahrenheit" →
calcul direct, pas de recherche web

**Rappels et timers**
"rappelle-moi dans X minutes", "minuteur X minutes", "alarme dans X" →
`threading.Timer` + `emit('toast', ...)` après le délai

**Blagues et humeur**
"raconte moi une blague", "dis moi quelque chose d'amusant" →
laisser le LLM fast répondre librement avec `temperature=0.9`

**Informations sur Mathis**
"qui suis-je", "parle moi de moi", "qu'est-ce que tu sais de moi" →
lire le system_prompt depuis config.yaml et résumer ce qu'ARIA sait

---

## Partie 2 — Résumés de recherche structurés et lisibles

### Ce que Cursor doit implémenter dans actions/web_research.py et llm.py

Quand une recherche web est nécessaire, le résultat affiché dans le chat
doit être un vrai résumé visuel, pas du texte brut.

**Format de résumé à utiliser systématiquement :**

```
## 🔍 [Titre du sujet]

[2-3 phrases de synthèse directe]

**Points clés :**
• Point 1
• Point 2
• Point 3

**Sources :** [lien1](url) · [lien2](url)
```

**Règles pour les résumés :**

- Toujours commencer par une réponse directe à la question posée
- Jamais plus de 250 mots dans le résumé
- Toujours citer 2-3 sources avec leurs liens cliquables
- Si c'est une actualité → mentionner la date
- Si c'est un fait encyclopédique → citer Wikipedia en premier
- Si plusieurs sources se contredisent → le signaler clairement

**Prompt de synthèse à utiliser dans search_and_synthesize() :**

Demander au LLM fast de répondre en JSON avec la structure :
```json
{
  "titre": "...",
  "synthese": "2-3 phrases directes",
  "points_cles": ["point 1", "point 2", "point 3"],
  "sources": [{"titre": "...", "url": "..."}]
}
```
Puis convertir ce JSON en markdown formaté côté Python avant d'envoyer
à l'UI — ne pas envoyer le JSON brut.

**Rendu dans l'UI (app.js) :**

La fonction `renderMarkdown()` doit déjà gérer `##`, `**`, `•` et `[texte](url)`.
S'assurer que les liens dans les résumés de recherche sont cliquables
via `ARIA.openExternal(url)`.

**Cas particuliers :**

- Questions sur l'aviation (METAR, météo aéro, NOTAMs) → format spécial
  avec les données brutes + traduction en français
- Questions sur les jeux vidéo → chercher sur DuckDuckGo uniquement,
  pas Wikipedia (souvent moins à jour)
- Questions d'actualité → sources news uniquement, mentionner "il y a X jours"

---

## Partie 3 — Routing intelligent question → source

Cursor doit implémenter une fonction `_select_answer_strategy(text)` dans llm.py
qui décide comment répondre selon la question :

| Type de question | Stratégie |
|-----------------|-----------|
| Heure/date/batterie | Réponse directe (0ms) |
| Météo locale | wttr.in → phrase naturelle |
| Définition simple | Wikipedia → résumé 3 phrases |
| Actualité récente | DDG News → résumé avec dates |
| Question complexe | Multi-sources → résumé structuré |
| Calcul | eval() sécurisé → réponse directe |
| Question perso | system_prompt → réponse mémorisée |

L'objectif est que 80% des questions courantes reçoivent une réponse
en moins de 2 secondes sans appeler le LLM heavy.

---

## Fichiers à modifier
- `python/llm.py` — ajouter `_select_answer_strategy()` et les intents rapides
- `python/actions/web_research.py` — format JSON + conversion markdown
- `python/actions/weather.py` — réponse météo en phrase naturelle
- `electron/renderer/app.js` — s'assurer que renderMarkdown() gère les liens

