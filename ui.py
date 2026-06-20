"""ARIA UI v7 — pywebview wrapper."""

from __future__ import annotations

import base64
import http.server
import json
import logging
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

import webview

import app_paths

logger = logging.getLogger(__name__)

_window: webview.Window | None = None
_api: AriaAPI | None = None
_instance: UI | None = None
_initial_status = "idle"
_show_on_ready = False
_js_lock = threading.Lock()

_training_process: subprocess.Popen | None = None
_training_log: list[str] = []
_training_status = "idle"

_installed_apps_cache = None
_installed_apps_cache_time = 0.0

_STATIC_PORT: int | None = None
_static_server_started = False


def _find_free_port(start: int = 8765) -> int:
    """Trouve un port libre entre start et start+19 (8765–8784 par défaut)."""
    import socket

    for port in range(start, start + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError("Aucun port libre disponible")


def _wallpaper_http_url(filename: str) -> str:
    port = _STATIC_PORT or 8765
    return f"http://127.0.0.1:{port}/wallpapers/{filename}"


def get_static_port() -> int:
    """Port du serveur statique (wallpapers)."""
    return _STATIC_PORT or 8765


def _start_static_server() -> None:
    """Démarre un serveur HTTP local pour servir data/ via http://127.0.0.1."""
    global _static_server_started, _STATIC_PORT
    if _static_server_started:
        return

    try:
        _STATIC_PORT = _find_free_port(8765)
    except RuntimeError as exc:
        logger.error("Impossible de trouver un port libre: %s", exc)
        return

    data_dir = app_paths.data_dir()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(data_dir), **kwargs)

        def log_message(self, format, *args):
            pass

    port = _STATIC_PORT

    def _run() -> None:
        try:
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
                logger.info("Serveur statique: http://127.0.0.1:%d", port)
                httpd.serve_forever()
        except Exception as exc:
            logger.error("Erreur serveur statique: %s", exc)

    threading.Thread(target=_run, daemon=True, name="ARIA-StaticHTTP").start()
    _static_server_started = True


def _html_path() -> Path:
    path = app_paths.resource_path("ui", "index.html")
    if path.exists():
        return path
    return Path(__file__).resolve().parent / "ui" / "index.html"


class AriaAPI:
    """API exposée à JavaScript via window.pywebview.api."""

    def __init__(self) -> None:
        self._on_deactivate = None
        self._on_quit = None

    def quit_aria(self) -> None:
        logger.info("Quit demandé par UI")
        if self._on_quit:
            self._on_quit()

    def toggle_activation(self) -> None:
        import sys

        mod = sys.modules.get("__main__")
        if mod is not None and hasattr(mod, "_on_hotkey"):
            mod._on_hotkey()
            return
        import main as _main

        _main._on_hotkey()

    def save_settings(self, settings_json: str) -> None:
        try:
            settings = json.loads(settings_json)
            state_path = app_paths.data_dir() / "ui_state.json"
            existing: dict = {}
            if state_path.exists():
                with state_path.open("r", encoding="utf-8") as f:
                    existing = json.load(f)
            for key, value in settings.items():
                if key == "presets" and isinstance(value, dict):
                    presets_existing = existing.get("presets", {})
                    if not isinstance(presets_existing, dict):
                        presets_existing = {}
                    for preset_key, preset_value in value.items():
                        if isinstance(preset_value, dict) and isinstance(
                            presets_existing.get(preset_key), dict
                        ):
                            merged = dict(presets_existing[preset_key])
                            for field, field_val in preset_value.items():
                                if field_val is None:
                                    merged.pop(field, None)
                                else:
                                    merged[field] = field_val
                            presets_existing[preset_key] = merged
                        else:
                            presets_existing[preset_key] = preset_value
                    existing["presets"] = presets_existing
                else:
                    existing[key] = value
            with state_path.open("w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)

            import llm

            if any(k in settings for k in ("model_fast", "model_heavy", "model_code", "auto_routing")):
                llm.apply_model_settings(
                    model_fast=settings.get("model_fast"),
                    model_heavy=settings.get("model_heavy"),
                    model_code=settings.get("model_code"),
                    auto_routing=settings.get("auto_routing"),
                )
        except Exception:
            logger.exception("Erreur sauvegarde settings")

    def save_wallpaper(self, base64_data: str, filename: str) -> str:
        """Sauvegarde une image uploadée dans data/wallpapers/ et retourne son URL."""
        try:
            wp_dir = app_paths.data_dir() / "wallpapers"
            wp_dir.mkdir(parents=True, exist_ok=True)

            if "," in base64_data:
                base64_data = base64_data.split(",", 1)[1]

            ext = Path(filename).suffix.lower() or ".jpg"
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                ext = ".jpg"

            safe_name = f"wallpaper_{int(time.time())}{ext}"
            out_path = wp_dir / safe_name

            out_path.write_bytes(base64.b64decode(base64_data))

            url = _wallpaper_http_url(safe_name)
            logger.info("Wallpaper sauvegardé: %s → %s", safe_name, url)
            return json.dumps({
                "success": True,
                "url": url,
                "filename": safe_name,
                "port": get_static_port(),
            })
        except Exception as exc:
            logger.error("Erreur save_wallpaper: %s", exc)
            return json.dumps({"success": False, "error": str(exc)})

    def get_wallpapers(self) -> str:
        """Retourne la liste des wallpapers personnalisés sauvegardés."""
        try:
            wp_dir = app_paths.data_dir() / "wallpapers"
            if not wp_dir.exists():
                return json.dumps([])
            files = []
            for f in sorted(wp_dir.iterdir()):
                if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    files.append({
                        "filename": f.name,
                        "url": _wallpaper_http_url(f.name),
                    })
            return json.dumps(files)
        except Exception as exc:
            logger.error("Erreur get_wallpapers: %s", exc)
            return json.dumps([])

    def delete_wallpaper(self, filename: str) -> str:
        """Supprime un wallpaper personnalisé."""
        try:
            wp_dir = app_paths.data_dir() / "wallpapers"
            target = wp_dir / Path(filename).name
            if target.exists():
                target.unlink()
                logger.info("Wallpaper supprimé: %s", filename)
                return json.dumps({"success": True})
            return json.dumps({"success": False, "error": "Fichier non trouvé"})
        except Exception as exc:
            logger.error("Erreur delete_wallpaper: %s", exc)
            return json.dumps({"success": False, "error": str(exc)})

    def get_presets(self) -> str:
        try:
            state_path = app_paths.data_dir() / "ui_state.json"
            if state_path.exists():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                presets = state.get("presets", {})
                if isinstance(presets, dict):
                    return json.dumps(presets, ensure_ascii=False)
        except Exception:
            logger.exception("Erreur chargement presets")
        return "{}"

    def get_mobile_connect_info(self) -> str:
        try:
            import aria_mobile_server as mobile_server

            info = mobile_server.get_connect_info()
            info["running"] = mobile_server.is_server_running()
            return json.dumps(info, ensure_ascii=False)
        except Exception:
            logger.exception("Erreur info mobile")
            return "{}"

    def get_installed_apps(self) -> str:
        """Scanne les apps réellement installées sur CE PC. Cache 1h."""
        import json
        import os
        import time
        import winreg

        global _installed_apps_cache, _installed_apps_cache_time

        if _installed_apps_cache and (time.time() - _installed_apps_cache_time) < 3600:
            return json.dumps(_installed_apps_cache)

        apps: set[str] = set()

        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, path in keys:
            try:
                key = winreg.OpenKey(hive, path)
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                        try:
                            name, _ = winreg.QueryValueEx(sub, "DisplayName")
                            if (
                                name
                                and 1 < len(name) < 60
                                and not name.startswith("{")
                                and "KB" not in name[:3]
                            ):
                                apps.add(name.strip())
                        except FileNotFoundError:
                            pass
                    except Exception:
                        pass
            except Exception:
                pass

        start_dirs = [
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
        ]
        for d in start_dirs:
            if not os.path.isdir(d):
                continue
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith(".lnk"):
                        name = f.replace(".lnk", "").strip()
                        if 1 < len(name) < 60:
                            apps.add(name)

        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-WindowStyle",
                    "Hidden",
                    "-Command",
                    "Get-AppxPackage | Select-Object -ExpandProperty Name",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if "." in line:
                    clean = line.split(".")[-1]
                    if 2 < len(clean) < 40:
                        apps.add(clean)
        except Exception:
            pass

        try:
            steam_apps_path = r"C:\Program Files (x86)\Steam\steamapps\common"
            if os.path.exists(steam_apps_path):
                for game_dir in os.listdir(steam_apps_path):
                    if 1 < len(game_dir) < 60:
                        apps.add(game_dir)
        except Exception:
            pass

        cleaned = sorted([a for a in apps if a], key=str.lower)
        _installed_apps_cache = cleaned
        _installed_apps_cache_time = time.time()
        logger.info("Scan apps installées: %d trouvées", len(cleaned))
        return json.dumps(cleaned)

    def refresh_installed_apps(self) -> str:
        """Force le rafraîchissement du cache d'apps."""
        global _installed_apps_cache_time

        _installed_apps_cache_time = 0
        return self.get_installed_apps()

    def check_nexus(self) -> str:
        import json
        from actions import nexus

        return json.dumps({
            "enabled": nexus.is_enabled(),
            "available": nexus.is_available() if nexus.is_enabled() else False,
        })

    def _update_config_field(self, key: str, value) -> None:
        import yaml

        cfg_path = app_paths.config_path()
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        cfg[key] = value
        with cfg_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

    def set_wake_word(self, enabled: bool) -> None:
        self._update_config_field("wake_word_enabled", enabled)

    def set_realtime_stt(self, enabled: bool) -> None:
        self._update_config_field("realtime_transcription", enabled)

    def set_daily_brief(self, enabled: bool) -> None:
        self._update_config_field("daily_brief_enabled", enabled)

    def set_setting(self, key: str, value) -> None:
        """Met à jour un champ de config.yaml."""
        self._update_config_field(key, value)

    def _update_stt_field(self, key: str, value) -> None:
        import yaml

        cfg_path = app_paths.config_path()
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        stt_cfg = cfg.setdefault("stt", {})
        stt_cfg[key] = value
        with cfg_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

    def set_stt_device_index(self, value: str) -> None:
        idx = None
        if value is not None and str(value).strip() != "":
            try:
                idx = int(value)
            except ValueError:
                idx = None
        self._update_stt_field("device_index", idx)

    def set_whisper_model(self, model: str) -> None:
        self._update_config_field("whisper_model", model)
        self._update_stt_field("model", model)

    def set_focus_mode(self, enabled: bool) -> None:
        import focus

        focus.set_focus_mode(bool(enabled))

    def is_focus_active(self) -> bool:
        import focus

        return focus.is_focus_active()

    def export_current_conversation(self) -> str:
        from actions.export_pdf import export_conversation
        import memory_engine

        messages = memory_engine.get_current_conversation_messages()
        title = memory_engine.get_current_conversation_title()
        return export_conversation(messages, title=title)

    def show_partial_transcription(self, text: str) -> None:
        self._js(
            f"if(window.aria) aria.showPartialTranscription({json.dumps(text)})"
        )

    def show_final_transcription(self, text: str) -> None:
        self._js(
            f"if(window.aria) aria.showFinalTranscription({json.dumps(text)})"
        )

    def update_checklist_ui(self, section: str, item: int, total: int) -> None:
        self._js(
            f"if(window.aria) aria.showChecklistProgress({json.dumps(section)}, {item}, {total})"
        )

    def hide_checklist_ui(self) -> None:
        self._js("if(window.aria) aria.hideChecklistProgress()")

    def update_focus_indicator(self, active: bool) -> None:
        self._js(f"if(window.aria) aria.updateFocusIndicator({json.dumps(active)})")

    def get_app_pin(self) -> str:
        import yaml

        try:
            with app_paths.config_path().open("r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return str(cfg.get("mobile_pin", "0000") or "0000")
        except Exception:
            return "0000"

    def get_config_flags(self) -> str:
        import yaml

        with app_paths.config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return json.dumps({
            "wake_word_enabled": cfg.get("wake_word_enabled", False),
            "realtime_transcription": cfg.get("realtime_transcription", False),
            "daily_brief_enabled": cfg.get("daily_brief_enabled", True),
            "german_mode": cfg.get("german_mode", False),
            "focus_mode": cfg.get("focus_mode", False),
            "device_index": (cfg.get("stt") or {}).get("device_index"),
            "whisper_model": cfg.get("whisper_model")
            or (cfg.get("stt") or {}).get("model", "small"),
        })

    def set_german_mode(self, enabled: bool) -> None:
        self._update_config_field("german_mode", enabled)

    def get_conversations(self) -> str:
        import json
        import memory_engine

        return json.dumps(memory_engine.get_conversations_list())

    def load_conversation(self, conv_id: str) -> str:
        import json
        import llm
        import memory_engine

        messages = memory_engine.switch_conversation(conv_id)
        llm.clear_history()
        llm.load_conversation_messages(messages)
        return json.dumps(messages)

    def new_conversation(self) -> str:
        import llm
        import memory_engine

        conv_id = memory_engine.new_conversation()
        llm.clear_history()
        return conv_id

    def delete_conversation(self, conv_id: str) -> str:
        import json
        import llm
        import memory_engine as _me

        was_current = _me.get_current_conversation_id() == conv_id
        success = _me.delete_conversation(conv_id)
        if success and was_current:
            llm.clear_history()
            messages = _me.get_engine().current_conversation.get("messages", [])
            llm.load_conversation_messages(messages)
        return json.dumps({"success": success})

    def delete_all_conversations(self) -> str:
        import json
        import llm
        import memory_engine as _me

        count = _me.delete_all_conversations()
        llm.clear_history()
        return json.dumps({"success": True, "count": count})

    def get_current_conversation_id(self) -> str:
        import memory_engine

        return memory_engine.get_current_conversation_id()

    def set_conversation_mode(self, conv_id: str, mode: str) -> None:
        import memory_engine

        memory_engine.set_conversation_mode(conv_id, mode)
        logger.info("Mode conversation '%s' = %s", conv_id, mode)

    def get_conversation_mode(self, conv_id: str) -> str | None:
        import memory_engine

        return memory_engine.get_conversation_mode(conv_id)

    def speak_text(self, text: str) -> None:
        import tts

        tts.speak(text, force=True)

    def start_mic(self) -> None:
        import stt

        if not stt.is_listening():
            stt.start_listening()
            logger.info("Micro démarré depuis UI")

    def stop_mic(self) -> None:
        import stt

        stt.stop_listening()
        logger.info("Micro arrêté depuis UI")

    def get_memory_stats(self) -> str:
        import json
        import memory_engine

        return json.dumps(memory_engine.get_memory_stats())

    def export_fine_tune(self) -> str:
        import memory_engine

        return memory_engine.export_fine_tune_dataset()

    def reset_memory(self) -> None:
        import memory_engine

        memory_engine.reset_memory()

    def add_voice_shortcut(self, trigger: str, action: str) -> None:
        import memory_engine

        engine = memory_engine.get_engine()
        engine.patterns.setdefault("voice_shortcuts", {})[trigger.lower()] = action
        memory_engine.save_json(memory_engine.PATTERNS_PATH, engine.patterns)

    def load_settings(self) -> str:
        try:
            state_path = app_paths.data_dir() / "ui_state.json"
            if state_path.exists():
                with state_path.open("r", encoding="utf-8") as f:
                    return f.read()
        except Exception:
            logger.exception("Erreur chargement settings")
        return "{}"

    def activate_preset(self, preset_key: str) -> str:
        try:
            from actions import presets

            return presets.activate(preset_key)
        except Exception as e:
            return f"Erreur preset : {e}"

    def clear_history(self) -> None:
        try:
            import llm

            llm.clear_history()
        except Exception:
            logger.exception("Erreur clear_history")

    def open_file(self, path: str) -> None:
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = app_paths.app_dir() / path
        subprocess.Popen(
            ["notepad.exe", str(file_path)],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def send_text(self, text: str) -> None:
        import llm, threading, ollama_manager

        def _run():
            if _instance:
                _instance.set_status("thinking")
            if not ollama_manager.is_running():
                if _instance:
                    _instance.show_toast("Démarrage Ollama...", toast_type="info")
                ollama_manager.start()
                ollama_manager.wait_until_ready(timeout=30)
            llm.ask(text, show_user=False)
            if _instance:
                _instance.set_status("idle")

        threading.Thread(target=_run, daemon=True).start()

    def send_file(self, base64_data: str, filename: str, mime_type: str, question: str) -> str:
        import base64
        import llm
        import os
        import tempfile
        import threading
        from pathlib import Path

        def _process() -> None:
            tmp_path: str | None = None
            try:
                if _instance:
                    _instance.set_status("thinking")

                ext = Path(filename).suffix or ".bin"
                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                tmp.write(base64.b64decode(base64_data))
                tmp.close()
                tmp_path = tmp.name
                logger.info("Fichier reçu: %s (%s)", filename, mime_type)

                if mime_type.startswith("image/"):
                    llm.ask_with_image(question, tmp_path)
                elif mime_type.startswith("video/"):
                    llm.ask_with_video(question, tmp_path)
                elif mime_type == "application/pdf" or filename.endswith(".pdf"):
                    llm.ask_with_pdf(question, tmp_path)
                elif filename.lower().endswith((".csv", ".xlsx", ".xls")):
                    from actions.data_analysis import analyze_file

                    result = analyze_file(tmp_path, question)
                    if _instance:
                        _instance.append_assistant_text(result)
                        _instance.finalize_assistant_message()
                        _instance.set_status("idle")
                else:
                    llm.ask_with_file(question, tmp_path, filename)
            except Exception as e:
                logger.error("send_file error: %s", e)
                if _instance:
                    _instance.show_error(f"Erreur: {e}")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

        threading.Thread(target=_process, daemon=True).start()
        return "ok"

    def send_files_with_prompt(self, files_json: str, prompt: str) -> str:
        import base64
        import json
        import llm
        import os
        import subprocess
        import sys
        import tempfile
        import threading
        from pathlib import Path

        def _process() -> None:
            try:
                files = json.loads(files_json)
                if not files:
                    return

                if _instance:
                    _instance.set_status("thinking")

                images_b64: list[str] = []
                text_contents: list[str] = []
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

                for f in files:
                    mime = f.get("type", "")
                    name = f.get("name", "fichier")
                    data = base64.b64decode(f["b64"])
                    ext = Path(name).suffix or ".bin"

                    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                    tmp.write(data)
                    tmp.close()
                    tmp_path = tmp.name

                    try:
                        if mime.startswith("image/"):
                            images_b64.append(f["b64"])
                        elif mime == "application/pdf" or name.lower().endswith(".pdf"):
                            from pypdf import PdfReader

                            reader = PdfReader(tmp_path)
                            text = "\n".join(p.extract_text() or "" for p in reader.pages[:10])
                            text_contents.append(f"[PDF: {name}]\n{text[:5000]}")
                        elif mime.startswith("video/"):
                            frame = tempfile.mktemp(suffix=".jpg")
                            subprocess.run(
                                ["ffmpeg", "-i", tmp_path, "-ss", "00:00:01", "-frames:v", "1", frame, "-y"],
                                capture_output=True,
                                timeout=15,
                                creationflags=flags,
                            )
                            if os.path.exists(frame):
                                with open(frame, "rb") as img:
                                    images_b64.append(base64.b64encode(img.read()).decode())
                                os.unlink(frame)
                        else:
                            with open(tmp_path, "r", encoding="utf-8", errors="ignore") as tf:
                                text_contents.append(f"[{name}]\n{tf.read(5000)}")
                    finally:
                        if os.path.exists(tmp_path):
                            os.unlink(tmp_path)

                csv_files = [f for f in files if f.get("name", "").lower().endswith((".csv", ".xlsx", ".xls"))]
                if csv_files and not images_b64:
                    from actions.data_analysis import analyze_file
                    import base64 as b64mod

                    tmp_csv = tempfile.NamedTemporaryFile(
                        suffix=Path(csv_files[0]["name"]).suffix, delete=False
                    )
                    tmp_csv.write(b64mod.b64decode(csv_files[0]["b64"]))
                    tmp_csv.close()
                    try:
                        result = analyze_file(tmp_csv.name, prompt)
                        if _instance:
                            _instance.append_assistant_text(result)
                            _instance.finalize_assistant_message()
                            _instance.set_status("idle")
                        return
                    finally:
                        if os.path.exists(tmp_csv.name):
                            os.unlink(tmp_csv.name)

                if images_b64:
                    homework = any(
                        kw in prompt.lower()
                        for kw in ("devoir", "corrige", "correction", "exercice", "bac", "note")
                    )
                    if homework and len(images_b64) == 1:
                        result = llm.analyze_homework_image(images_b64[0], prompt)
                        if _instance:
                            _instance.append_assistant_text(result)
                            _instance.finalize_assistant_message()
                            _instance.set_status("idle")
                    else:
                        llm.ask_with_images_and_text(prompt, images_b64, text_contents)
                elif text_contents:
                    combined = "\n\n".join(text_contents)
                    llm.ask(f"{prompt}\n\nContenu des fichiers:\n{combined}", show_user=False)
                elif _instance:
                    _instance.show_error("Aucun contenu exploitable dans les fichiers envoyés.")
            except Exception as e:
                logger.error("send_files_with_prompt error: %s", e)
                if _instance:
                    _instance.show_error(f"Erreur: {e}")

        threading.Thread(target=_process, daemon=True).start()
        return "ok"

    def set_tts_enabled(self, enabled: bool) -> None:
        import tts

        tts.set_enabled(enabled)

    def get_training_stats(self) -> str:
        import yaml

        dataset_path = app_paths.data_dir() / "fine_tune_dataset.jsonl"
        last_count_path = app_paths.data_dir() / "last_train_count.txt"
        last_date_path = app_paths.data_dir() / "last_train_date.txt"

        total = 0
        if dataset_path.exists():
            with dataset_path.open(encoding="utf-8") as f:
                total = sum(1 for _ in f)

        last_count = 0
        if last_count_path.exists():
            try:
                last_count = int(last_count_path.read_text(encoding="utf-8"))
            except ValueError:
                pass

        last_date = "Jamais"
        if last_date_path.exists():
            last_date = last_date_path.read_text(encoding="utf-8").strip()[:10]

        try:
            with app_paths.config_path().open(encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            active_model = cfg.get("active_model") or cfg.get("model", "qwen3:14b")
        except Exception:
            active_model = "auto"

        custom_exists = False
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=flags,
            )
            custom_exists = "aria-custom" in result.stdout
        except Exception:
            pass

        return json.dumps({
            "total_examples": total,
            "new_since_last": max(0, total - last_count),
            "last_train_date": last_date,
            "active_model": active_model,
            "custom_model_exists": custom_exists,
        })

    def get_available_models(self) -> str:
        """Modèles Ollama locaux + config par rôle (+ options sélecteur en-tête)."""
        import json

        running = False
        local: list[str] = []
        try:
            import ollama_manager

            running = ollama_manager.is_running()
            if not running:
                try:
                    running = ollama_manager.start_ollama()
                except Exception:
                    running = False
            local = ollama_manager.list_local_models() if running else []
        except Exception as exc:
            logger.error("get_available_models error: %s", exc)
            running = False
            local = []

        configured: dict = {}
        current = "auto"
        options: list[dict[str, str]] = []
        try:
            import llm

            configured = dict(llm.MODELS)
            current = llm.FORCED_MODEL or "auto"

            def norm(name: str) -> str:
                return name.removesuffix(":latest") if name else ""

            options.append({
                "id": "auto",
                "label": "Auto",
                "subtitle": "Rapide par défaut, réflexion si la question est complexe",
            })
            seen = {norm("auto")}
            if local:
                for name in local:
                    n = norm(name)
                    if n and n not in seen:
                        seen.add(n)
                        options.append({
                            "id": name,
                            "label": n,
                            "subtitle": "Installé localement",
                        })
            else:
                for mid, label, subtitle in (
                    (llm.MODEL_FAST, "Rapide", llm.MODEL_FAST),
                    (llm.REASONING_MODEL, "Raisonnement", llm.REASONING_MODEL),
                    (llm.MODEL_CODE, "Code", llm.MODEL_CODE),
                ):
                    n = norm(mid)
                    if n and n not in seen:
                        seen.add(n)
                        options.append({"id": mid, "label": label, "subtitle": subtitle})

            if current != "auto" and norm(current) not in seen:
                options.append({
                    "id": current,
                    "label": norm(current),
                    "subtitle": "Modèle actif",
                })
        except Exception as exc:
            logger.error("get_available_models llm error: %s", exc)

        result = {
            "ollama_running": running,
            "local_models": local,
            "configured": configured,
            "current": current,
            "options": options,
        }
        logger.info("get_available_models: running=%s, models=%s", running, local)
        return json.dumps(result)

    def get_static_port(self) -> int:
        return get_static_port()

    def set_model(self, role: str, model_name: str) -> str:
        """Change le modèle pour un rôle (intent/fast/heavy/vision)."""
        import llm

        try:
            llm.set_model_role(role, model_name)
            return json.dumps({"success": True})
        except Exception as exc:
            logger.error("set_model error: %s", exc)
            return json.dumps({"success": False, "error": str(exc)})

    def switch_model(self, model_name: str) -> str:
        """Choisit le modèle utilisé (comme Claude). 'auto' = escalade intelligente."""
        import llm

        try:
            llm.set_active_model(model_name)
            return "ok"
        except Exception as e:
            logger.error("switch_model error: %s", e)
            return str(e)

    def start_training(self) -> str:
        global _training_process, _training_log, _training_status
        from datetime import datetime

        _training_log = ["🚀 Démarrage entraînement...\n"]
        _training_status = "running"

        def _run() -> None:
            global _training_process, _training_log, _training_status
            try:
                python_exe = app_paths.app_dir() / ".venv" / "Scripts" / "python.exe"
                if not python_exe.exists():
                    python_exe = Path(__file__).resolve().parent / ".venv" / "Scripts" / "python.exe"
                train_script = app_paths.app_dir() / "train_aria.py"
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

                _training_process = subprocess.Popen(
                    [str(python_exe), str(train_script)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=str(app_paths.app_dir()),
                    creationflags=flags,
                )

                if _training_process.stdout:
                    for line in _training_process.stdout:
                        _training_log.append(line)
                        if len(_training_log) > 200:
                            _training_log = _training_log[-200:]

                _training_process.wait()

                if _training_process.returncode == 0:
                    _training_status = "done"
                    last_date_path = app_paths.data_dir() / "last_train_date.txt"
                    last_date_path.write_text(datetime.now().isoformat(), encoding="utf-8")
                    dataset_path = app_paths.data_dir() / "fine_tune_dataset.jsonl"
                    if dataset_path.exists():
                        with dataset_path.open(encoding="utf-8") as f:
                            count = sum(1 for _ in f)
                        (app_paths.data_dir() / "last_train_count.txt").write_text(
                            str(count), encoding="utf-8"
                        )
                else:
                    _training_status = "error"
            except Exception as e:
                _training_log.append(f"\n❌ Erreur: {e}")
                _training_status = "error"

        threading.Thread(target=_run, daemon=True).start()
        return "ok"

    def get_training_log(self) -> str:
        return json.dumps({
            "log": "".join(_training_log[-100:]),
            "status": _training_status,
        })

    def stop_training(self) -> None:
        global _training_process, _training_status
        if _training_process:
            try:
                _training_process.terminate()
                _training_process = None
            except Exception:
                pass
        _training_status = "idle"

    def stop_speaking(self) -> None:
        import tts

        tts.stop()
        if _instance:
            _instance.finalize_assistant_message()
            _instance.set_status("idle")


class UI:
    def __init__(self, on_deactivate=None, on_quit=None) -> None:
        global _api
        _api = AriaAPI()
        _api._on_deactivate = on_deactivate
        _api._on_quit = on_quit

    def run(self) -> None:
        global _window
        _start_static_server()
        html = _html_path()
        if not html.exists():
            raise FileNotFoundError(f"Interface introuvable : {html}")

        logger.info("Création de la fenêtre pywebview...")
        logger.info("HTML: %s", html.resolve())

        _window = webview.create_window(
            title="ARIA",
            url=str(html.resolve()) + "?v=" + str(int(time.time())),
            js_api=_api,
            width=1920,
            height=1080,
            x=0,
            y=0,
            resizable=True,
            fullscreen=False,
            minimized=False,
            on_top=False,
            frameless=False,
            easy_drag=False,
            background_color="#1C1C1E",
            transparent=False,
        )
        logger.info("Fenêtre créée: %s", _window)

        try:
            import main as _main

            if hasattr(_main, "_on_aria_closing"):
                _window.events.closing += _main._on_aria_closing
                logger.info("Callback fermeture ARIA branché sur events.closing")
        except Exception:
            logger.exception("Impossible de brancher l'event closing")

        gui_backend = getattr(webview, "platforms", None)
        if gui_backend is None:
            gui_backend = getattr(getattr(webview, "guilib", None), "__name__", webview.guilib)
        logger.info("Backends GUI disponibles: %s", gui_backend)

        logger.info("Appel de webview.start()...")
        try:
            webview.start(
                _on_webview_ready,
                args=(_window,),
                debug=True,
                http_server=False,
                private_mode=False,
                storage_path=str(app_paths.data_dir() / "webview_cache"),
            )
            logger.info("webview.start() terminé normalement")
        except Exception as exc:
            logger.error("webview.start() a levé une exception: %s", exc, exc_info=True)
            raise

    def _js(self, code: str) -> None:
        if not _window:
            return
        with _js_lock:
            try:
                _window.evaluate_js(code)
            except Exception:
                logger.debug("evaluate_js failed", exc_info=True)

    def show(self) -> None:
        self._js("if(window.aria) aria.show()")

    def hide(self) -> None:
        self._js("if(window.aria) aria.hide()")

    def show_user_text(self, text: str) -> None:
        escaped = json.dumps(text)
        self._js(f"if(window.aria) aria.addUserBubble({escaped})")

    def append_assistant_text(self, token: str) -> None:
        escaped = json.dumps(token)
        self._js(f"if(window.aria) aria.appendToken({escaped})")

    def finalize_assistant_message(self) -> None:
        self._js("if(window.aria) aria.finalizeMessage()")

    def set_status(self, state: str) -> None:
        escaped = json.dumps(state)
        self._js(f"if(window.aria) aria.setStatus({escaped})")

    def update_waveform(self, rms: float) -> None:
        try:
            normalized = rms / 32768.0 if rms > 1.0 else rms
            self._js(f"if(window.aria) aria.updateWaveform({normalized:.6f})")
        except Exception:
            pass

    def show_toast(self, message: str, duration: int = 3000, toast_type: str = "info") -> None:
        self._js(
            f"if(window.aria) aria.showToast({json.dumps(message)}, "
            f"{json.dumps(toast_type)}, {int(duration)})"
        )

    def show_error(self, text: str) -> None:
        self._js(f"if(window.aria) aria.showError({json.dumps(text)})")

    def show_notification(self, text: str, duration: int = 3) -> None:
        self.show_toast(text, duration * 1000)

    def minimize(self) -> None:
        if _window:
            _window.minimize()

    def _poll_transcript_queue(self) -> None:
        try:
            import stt

            while not stt._transcript_queue.empty():
                text = stt._transcript_queue.get_nowait()
                self._js(
                    "if(window.aria){"
                    f"const i=document.getElementById('text-input');"
                    f"i.value={json.dumps(text)};"
                    "i.dispatchEvent(new Event('input'));"
                    "i.focus();"
                    "i.style.height='auto';"
                    "i.style.height=Math.min(i.scrollHeight,200)+'px';"
                    "}"
                )
                logger.info("Transcription affichée: '%s'", text[:120])
        except Exception as exc:
            logger.debug("Queue poll error: %s", exc)
        threading.Timer(0.5, self._poll_transcript_queue).start()


def _on_webview_ready(window: webview.Window) -> None:
    logger.info("UI pywebview prête")
    window.maximize()
    if _instance:
        if _show_on_ready:
            _instance.show()
        _instance.set_status(_initial_status)
        _instance._poll_transcript_queue()


def init(on_deactivate=None, on_quit=None) -> UI:
    global _instance
    _instance = UI(on_deactivate=on_deactivate, on_quit=on_quit)
    return _instance


def run() -> None:
    if _instance:
        _instance.run()


def show() -> None:
    global _show_on_ready
    _show_on_ready = True
    if _instance and _window:
        _instance.show()


def hide() -> None:
    if _instance:
        _instance.hide()


def show_user_text(text: str) -> None:
    if _instance:
        _instance.show_user_text(text)


def append_assistant_text(token: str) -> None:
    if _instance:
        _instance.append_assistant_text(token)


def finalize_assistant_message() -> None:
    if _instance:
        _instance.finalize_assistant_message()


def set_status(state: str) -> None:
    global _initial_status
    _initial_status = state
    if _instance and _window:
        _instance.set_status(state)


def update_waveform(rms: float) -> None:
    if _instance:
        _instance.update_waveform(rms)


def update_info_widget(weather: str = "", time_str: str = "") -> None:
    if _instance and weather:
        _instance._js(f"if(window.aria) aria.updateWeather({json.dumps(weather)})")


def show_notification(text: str, duration: int = 3) -> None:
    if _instance:
        _instance.show_notification(text, duration)


def show_toast(message: str, duration: int = 3000, toast_type: str = "info") -> None:
    if _instance:
        _instance.show_toast(message, duration, toast_type)


def show_error(text: str) -> None:
    if _instance:
        _instance.show_error(text)


def show_partial_transcription(text: str) -> None:
    if _instance:
        _instance.show_partial_transcription(text)


def show_final_transcription(text: str) -> None:
    if _instance:
        _instance.show_final_transcription(text)


def update_focus_indicator(active: bool) -> None:
    if _instance:
        _instance.update_focus_indicator(active)


def update_checklist_ui(section: str, item: int, total: int) -> None:
    if _instance:
        _instance.update_checklist_ui(section, item, total)


def hide_checklist_ui() -> None:
    if _instance:
        _instance.hide_checklist_ui()


def notify_mic_state(active: bool) -> None:
    if _instance:
        _instance._js(f"if(window.aria) aria.onMicExternalToggle({json.dumps(active)});")
