"""ARIA UI v7 — pywebview wrapper."""

from __future__ import annotations

import json
import logging
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
        except Exception:
            logger.exception("Erreur sauvegarde settings")

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
        import json
        import os
        import winreg

        apps = set()

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
                            if name and len(name) > 1:
                                apps.add(name.strip())
                        except Exception:
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
                        apps.add(f.replace(".lnk", "").strip())

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
                if line and "." in line:
                    parts = line.split(".")
                    clean = parts[-1] if len(parts) > 1 else line
                    if len(clean) > 2:
                        apps.add(clean)
        except Exception:
            pass

        try:
            from actions.apps import KNOWN_APPS

            for k in KNOWN_APPS:
                if isinstance(k, str) and len(k) > 1:
                    apps.add(k.title())
        except Exception:
            pass

        cleaned = sorted(
            [
                a
                for a in apps
                if a
                and len(a) > 1
                and len(a) < 60
                and not a.startswith("{")
                and not a.startswith("KB")
            ],
            key=str.lower,
        )

        return json.dumps(cleaned)

    def get_conversations(self) -> str:
        import json
        import memory_engine

        return json.dumps(memory_engine.get_conversations_list())

    def load_conversation(self, conv_id: str) -> str:
        import json
        import llm
        import memory_engine

        messages = memory_engine.load_conversation(conv_id)
        llm.clear_history()
        llm.load_conversation_messages(messages)
        return json.dumps(messages)

    def new_conversation(self) -> str:
        import llm
        import memory_engine

        memory_engine.new_conversation()
        llm.clear_history()
        return "ok"

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

                if images_b64:
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
            active_model = cfg.get("model", "qwen3:14b")
        except Exception:
            active_model = "qwen3:14b"

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

    def switch_model(self, model_name: str) -> str:
        """Change le modèle actif dans config.yaml et llm.py en temps réel."""
        import llm
        import yaml

        try:
            config_path = app_paths.config_path()
            with config_path.open("r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            cfg["model"] = model_name
            with config_path.open("w", encoding="utf-8") as f:
                yaml.dump(cfg, f, allow_unicode=True)
            llm.MODELS["heavy"] = model_name
            llm.MODEL = model_name
            llm.MODEL_HEAVY = model_name
            llm.clear_history()
            logger.info("Modèle changé: %s", model_name)
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
        self._js(f"if(window.aria) aria.updateWaveform({rms:.1f})")

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
