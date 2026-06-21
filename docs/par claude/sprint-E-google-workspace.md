# Sprint E — Google Workspace Complet

## APIs activées dans aria-assistant-500116
- Google Docs API ✅
- Google Drive API ✅
- Google Calendar API ✅
- Gmail API ✅
- Google Sheets API ✅
- Google Forms API ✅

## credentials.json
Fichier fourni : `client_secret_109152193125-sl4j6fekgki8880cl5h7p8vkegmfdobo.apps.googleusercontent.com.json`
À renommer en `python/credentials.json`

## Installation
```bash
.venv\Scripts\python.exe -m pip install google-auth google-auth-oauthlib google-api-python-client --break-system-packages
```

## actions/google_auth.py

```python
"""
google_auth.py — Authentification OAuth2 Google commune à tous les services.
"""
import os, logging
from pathlib import Path
import app_paths

logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/forms',
]

CREDENTIALS_FILE = Path(__file__).parent.parent / 'credentials.json'
TOKEN_FILE = app_paths.data_dir() / 'google_token.json'


def is_configured() -> bool:
    return CREDENTIALS_FILE.exists()


def get_credentials():
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"credentials.json non trouvé dans {CREDENTIALS_FILE}. "
                    "Lance setup_google.py pour configurer Google."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0, open_browser=True)

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())

    return creds


def build_service(service_name: str, version: str):
    from googleapiclient.discovery import build
    creds = get_credentials()
    return build(service_name, version, credentials=creds)
```

## actions/gcalendar.py

```python
"""
gcalendar.py — Google Calendar : créer, lire, supprimer des événements.
"""
import logging
from datetime import datetime, timedelta
from actions.google_auth import build_service, is_configured

logger = logging.getLogger(__name__)


def _svc():
    return build_service('calendar', 'v3')


def get_upcoming_events(max_results: int = 10) -> list[dict]:
    """Retourne les prochains événements du calendrier principal."""
    if not is_configured():
        return []
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        result = _svc().events().list(
            calendarId='primary',
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = result.get('items', [])
        logger.info("Calendar: %d événements à venir", len(events))
        return events
    except Exception as e:
        logger.error("Calendar get_upcoming: %s", e)
        return []


def create_event(
    title: str,
    start: datetime,
    end: datetime = None,
    description: str = '',
    location: str = '',
) -> dict:
    """Crée un événement dans le calendrier principal."""
    if end is None:
        end = start + timedelta(hours=1)
    event_body = {
        'summary': title,
        'description': description,
        'location': location,
        'start': {'dateTime': start.isoformat(), 'timeZone': 'Europe/Paris'},
        'end':   {'dateTime': end.isoformat(),   'timeZone': 'Europe/Paris'},
    }
    try:
        created = _svc().events().insert(calendarId='primary', body=event_body).execute()
        logger.info("Événement créé: %s", created.get('htmlLink'))
        return created
    except Exception as e:
        logger.error("Calendar create_event: %s", e)
        raise


def format_events_for_aria(events: list[dict]) -> str:
    """Formate les événements pour une réponse naturelle d'ARIA."""
    if not events:
        return "Aucun événement à venir dans ton calendrier."
    lines = ["Voici tes prochains événements :"]
    for ev in events:
        start = ev['start'].get('dateTime', ev['start'].get('date', ''))
        try:
            dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            date_str = dt.strftime('%d/%m à %H:%M')
        except Exception:
            date_str = start
        lines.append(f"• **{ev.get('summary', 'Sans titre')}** — {date_str}")
        if ev.get('location'):
            lines.append(f"  📍 {ev['location']}")
    return '\n'.join(lines)
```

## actions/gdrive.py

```python
"""
gdrive.py — Google Drive : upload, download, recherche de fichiers.
"""
import logging, io
from pathlib import Path
from actions.google_auth import build_service, is_configured

logger = logging.getLogger(__name__)


def _svc():
    return build_service('drive', 'v3')


def search_files(query: str, max_results: int = 10) -> list[dict]:
    """Recherche des fichiers dans Google Drive."""
    if not is_configured():
        return []
    try:
        results = _svc().files().list(
            q=f"name contains '{query}' and trashed=false",
            pageSize=max_results,
            fields="files(id, name, mimeType, webViewLink, modifiedTime)"
        ).execute()
        files = results.get('files', [])
        logger.info("Drive search '%s': %d fichiers", query, len(files))
        return files
    except Exception as e:
        logger.error("Drive search: %s", e)
        return []


def upload_file(local_path: str, folder_id: str = None) -> dict:
    """Upload un fichier local vers Google Drive."""
    from googleapiclient.http import MediaFileUpload
    path = Path(local_path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier non trouvé: {local_path}")

    file_metadata = {'name': path.name}
    if folder_id:
        file_metadata['parents'] = [folder_id]

    media = MediaFileUpload(str(path))
    try:
        created = _svc().files().create(
            body=file_metadata, media_body=media, fields='id,name,webViewLink'
        ).execute()
        logger.info("Drive upload: %s → %s", path.name, created.get('webViewLink'))
        return created
    except Exception as e:
        logger.error("Drive upload: %s", e)
        raise


def list_recent_files(max_results: int = 10) -> list[dict]:
    """Liste les fichiers récemment modifiés."""
    if not is_configured():
        return []
    try:
        results = _svc().files().list(
            orderBy='modifiedTime desc',
            pageSize=max_results,
            fields="files(id, name, mimeType, webViewLink, modifiedTime)",
            q="trashed=false"
        ).execute()
        return results.get('files', [])
    except Exception as e:
        logger.error("Drive list_recent: %s", e)
        return []
```

## actions/ggmail.py

```python
"""
ggmail.py — Gmail : lire et envoyer des emails.
"""
import logging, base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from actions.google_auth import build_service, is_configured

logger = logging.getLogger(__name__)


def _svc():
    return build_service('gmail', 'v1')


def get_unread_emails(max_results: int = 5) -> list[dict]:
    """Retourne les emails non lus récents."""
    if not is_configured():
        return []
    try:
        results = _svc().users().messages().list(
            userId='me', q='is:unread', maxResults=max_results
        ).execute()
        messages = []
        for msg_ref in results.get('messages', []):
            msg = _svc().users().messages().get(
                userId='me', id=msg_ref['id'], format='metadata',
                metadataHeaders=['From', 'Subject', 'Date']
            ).execute()
            headers = {h['name']: h['value'] for h in msg['payload']['headers']}
            messages.append({
                'id': msg['id'],
                'from': headers.get('From', ''),
                'subject': headers.get('Subject', ''),
                'date': headers.get('Date', ''),
                'snippet': msg.get('snippet', ''),
            })
        logger.info("Gmail: %d emails non lus", len(messages))
        return messages
    except Exception as e:
        logger.error("Gmail get_unread: %s", e)
        return []


def send_email(to: str, subject: str, body: str, html: bool = False) -> bool:
    """Envoie un email depuis le compte Gmail authentifié."""
    if not is_configured():
        raise RuntimeError("Google non configuré.")
    try:
        if html:
            msg = MIMEMultipart('alternative')
            msg.attach(MIMEText(body, 'html'))
        else:
            msg = MIMEText(body)
        msg['to'] = to
        msg['subject'] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        _svc().users().messages().send(userId='me', body={'raw': raw}).execute()
        logger.info("Email envoyé à %s: %s", to, subject)
        return True
    except Exception as e:
        logger.error("Gmail send: %s", e)
        raise


def format_emails_for_aria(emails: list[dict]) -> str:
    if not emails:
        return "Aucun email non lu."
    lines = [f"Tu as {len(emails)} email(s) non lu(s) :"]
    for e in emails:
        lines.append(f"• **{e['subject']}** de {e['from']}")
        if e.get('snippet'):
            lines.append(f"  _{e['snippet'][:100]}..._")
    return '\n'.join(lines)
```

## actions/gsheets.py

```python
"""
gsheets.py — Google Sheets : lire et écrire dans des feuilles de calcul.
"""
import logging
from actions.google_auth import build_service, is_configured

logger = logging.getLogger(__name__)


def _svc():
    return build_service('sheets', 'v4')


def create_spreadsheet(title: str) -> dict:
    """Crée une nouvelle feuille de calcul."""
    try:
        result = _svc().spreadsheets().create(
            body={'properties': {'title': title}}
        ).execute()
        logger.info("Sheet créé: %s", result.get('spreadsheetUrl'))
        return {
            'id': result['spreadsheetId'],
            'title': title,
            'url': result.get('spreadsheetUrl', ''),
        }
    except Exception as e:
        logger.error("Sheets create: %s", e)
        raise


def read_range(spreadsheet_id: str, range_: str = 'Sheet1!A1:Z100') -> list[list]:
    """Lit une plage de données."""
    try:
        result = _svc().spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_
        ).execute()
        return result.get('values', [])
    except Exception as e:
        logger.error("Sheets read: %s", e)
        return []


def append_rows(spreadsheet_id: str, values: list[list], range_: str = 'Sheet1') -> bool:
    """Ajoute des lignes à la fin d'une feuille."""
    try:
        _svc().spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_,
            valueInputOption='USER_ENTERED',
            body={'values': values}
        ).execute()
        logger.info("Sheets append: %d lignes", len(values))
        return True
    except Exception as e:
        logger.error("Sheets append: %s", e)
        raise


def write_range(spreadsheet_id: str, range_: str, values: list[list]) -> bool:
    """Écrit des données dans une plage spécifique."""
    try:
        _svc().spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_,
            valueInputOption='USER_ENTERED',
            body={'values': values}
        ).execute()
        return True
    except Exception as e:
        logger.error("Sheets write: %s", e)
        raise
```

## Intents Google dans llm.py

```python
# KNOWN_INTENTS à ajouter :
'gcal_get_events',    # "quels sont mes événements ?"
'gcal_create_event',  # "crée un événement [titre] le [date]"
'gmail_read',         # "lis mes emails" / "j'ai des emails ?"
'gmail_send',         # "envoie un email à [destinataire] pour [sujet]"
'gdrive_search',      # "cherche [fichier] dans mon drive"
'gdrive_recent',      # "mes fichiers récents sur drive"
'gsheets_create',     # "crée un tableau Google Sheets [titre]"
'gsheets_read',       # "lis le tableau [titre/id]"

# Patterns _fast_intent() :
if any(kw in text_lower for kw in ['mes événements', 'mon calendrier', 'agenda', 'rendez-vous']):
    return 'gcal_get_events', {}
if any(kw in text_lower for kw in ['mes emails', 'mes mails', 'boîte mail', 'nouveaux emails']):
    return 'gmail_read', {}
m = re.search(r'envoie\s+(?:un\s+)?(?:email|mail)\s+(?:à|a)\s+(.+?)\s+(?:pour|sur|objet)\s+(.+)', text_lower)
if m:
    return 'gmail_send', {'to': m.group(1), 'subject': m.group(2)}
if any(kw in text_lower for kw in ['cherche', 'trouve']) and 'drive' in text_lower:
    return 'gdrive_search', {}

# Exécution dans _execute_action() :
elif intent == 'gcal_get_events':
    from actions.gcalendar import get_upcoming_events, format_events_for_aria
    events = get_upcoming_events(10)
    return format_events_for_aria(events)

elif intent == 'gcal_create_event':
    # Parser la date/heure depuis le texte avec le LLM
    return _create_calendar_event_from_text(text)

elif intent == 'gmail_read':
    from actions.ggmail import get_unread_emails, format_emails_for_aria
    emails = get_unread_emails(5)
    return format_emails_for_aria(emails)

elif intent == 'gmail_send':
    to = params.get('to', '')
    subject = params.get('subject', '')
    return _compose_and_send_email(text, to, subject)

elif intent == 'gdrive_search':
    from actions.gdrive import search_files
    query = re.sub(r'.*(?:cherche|trouve)\s+', '', text, flags=re.I).replace('dans mon drive', '').strip()
    files = search_files(query, 5)
    if not files:
        return f"Aucun fichier '{query}' trouvé dans ton Drive."
    lines = [f"Fichiers trouvés pour '{query}' :"]
    for f in files:
        lines.append(f"• [{f['name']}]({f.get('webViewLink','')}) ({f.get('mimeType','').split('.')[-1]})")
    return '\n'.join(lines)
```

## Script d'authentification initiale — python/setup_google.py

```python
"""
setup_google.py — Authentification Google initiale (une seule fois).
Lance : .venv\Scripts\python.exe setup_google.py
"""
import sys
sys.path.insert(0, 'python')
from actions.google_auth import get_credentials

print("Authentification Google OAuth2...")
print("Une fenêtre Chrome va s'ouvrir pour te connecter.")
print()
creds = get_credentials()
print("✅ Authentification réussie !")
print("Token sauvegardé dans data/google_token.json")
print()
print("APIs disponibles : Docs, Drive, Calendar, Gmail, Sheets, Forms")
```

## Prompt Cursor

> Sprint E — Intégration Google Workspace complète.
>
> 1. Renommer le fichier credentials fourni en `python/credentials.json`
> 2. Créer `python/actions/google_auth.py` — authentification OAuth2 commune
> 3. Créer `python/actions/gcalendar.py` — Calendar (lire + créer événements)
> 4. Créer `python/actions/gdrive.py` — Drive (search + upload + récents)
> 5. Créer `python/actions/ggmail.py` — Gmail (lire non lus + envoyer)
> 6. Créer `python/actions/gsheets.py` — Sheets (créer + lire + écrire)
> 7. Créer `python/setup_google.py` — script d'auth initiale
> 8. Dans `python/llm.py` ajouter les 8 intents Google avec leurs patterns et exécutions
> 9. Dans `python/requirements.txt` ajouter : `google-auth`, `google-auth-oauthlib`, `google-api-python-client`
>
> Créer : python/credentials.json (copie du fichier fourni), python/actions/google_auth.py,
> python/actions/gcalendar.py, python/actions/gdrive.py, python/actions/ggmail.py,
> python/actions/gsheets.py, python/setup_google.py
> Modifier : python/llm.py, python/requirements.txt
