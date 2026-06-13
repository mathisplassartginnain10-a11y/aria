# ARIA Mobile

App React Native / Expo pour contrôler ARIA sur ton PC via WiFi.

## Prérequis

- Node.js 18+
- ARIA lancé sur le PC (serveur mobile auto) ou `start_mobile.bat`
- Téléphone et PC sur le **même réseau WiFi**

## Développement

```bash
npm install
npx expo start
```

Scanne le QR code avec **Expo Go** (Android) pour tester sans build.

## Build APK

### Option 1 — EAS Build (cloud, recommandé)

```bash
npm install -g eas-cli
eas login
eas build:configure   # une seule fois
npm run build:apk
```

Télécharge l'APK depuis le lien Expo une fois le build terminé.

### Option 2 — Build local

```bash
npm install
npx expo run:android
```

Nécessite Android Studio + SDK installés.

## Fonctionnalités

- **Scan réseau automatique** au premier lancement (sans IP enregistrée)
- **Scanner QR** du PC (Paramètres → App mobile dans ARIA)
- Chat texte + vocal (Whisper sur le PC)
- Presets synchronisés depuis le PC (Vol, Gaming, Étude…)
- Actions rapides (météo, lancer apps, volume)
- TTS des réponses (activable dans Réglages)

## Configuration PC

Dans `config.yaml` :

```yaml
mobile_auto_start: true
mobile_port: 5000
mobile_pin: "0000"
```

Format QR : `aria://192.168.x.x:5000`

## API utilisée

| Endpoint | Description |
|----------|-------------|
| `GET /ping` | Détection PC (+ `qr_payload`) |
| `GET /connect-info` | Infos connexion sans auth |
| `POST /auth` | Connexion PIN |
| `POST /transcribe` | Audio → texte (Whisper PC) |
| `POST /ask/stream` | Chat streaming |
| `GET /presets` | Liste des modes |
| `POST /presets/:name/activate` | Active un mode sur le PC |
