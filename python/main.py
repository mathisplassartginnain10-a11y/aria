"""
main.py — Point d'entrée ARIA en mode Electron.
Lance le serveur WebSocket et démarre les services backend.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

# Racine projet (assistant-vocal/) — modules llm, stt, etc.
ROOT = Path(__file__).resolve().parent.parent
PYTHON_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import os

os.chdir(ROOT)

# Fix encodage Windows
if not getattr(sys, "_aria_bootstrapped", False):
    sys._aria_bootstrapped = True
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import platform as _platform

_platform._wmi = None

import ctypes

try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ARIA.VoiceAssistant.v2")
except Exception:
    pass

import atexit
import logging
import signal
import threading
import time
import traceback

import yaml

import app_paths
import generate_sounds
import memory
import memory_engine
import llamacpp_manager
import sounds
import stt
import tts
import ui_bridge

CONFIG_PATH = app_paths.config_path()
LOG_PATH = app_paths.app_dir() / "assistant-vocal.log"

_mic_active = False
_mic_lock = threading.Lock()
_listen_thread: threading.Thread | None = None
_config: dict = {}
_logger: logging.Logger | None = None
_last_hotkey_time: float = 0.0
_HOTKEY_DEBOUNCE_S = 0.35
_shutdown_done = False


def _setup_logging(debug: bool = False, log_level: str | None = None) -> logging.Logger:
    class _SafeStreamHandler(logging.StreamHandler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                super().emit(record)
            except (ValueError, OSError):
                pass

    level = getattr(logging, str(log_level).upper(), logging.INFO) if log_level else (
        logging.DEBUG if debug else logging.INFO
    )
    fmt = logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    console = _SafeStreamHandler(sys.__stderr__)
    console.setFormatter(fmt)
    root.addHandler(console)
    return logging.getLogger(__name__)


def _load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    ollama_path = str(config.get("ollama_path", ""))
    if "USERNAME" in ollama_path:
        ollama_path = ollama_path.replace("USERNAME", os.environ.get("USERNAME", ""))
    config["ollama_path"] = Path(ollama_path) if ollama_path else Path()
    return config


def _stop_ollama_processes() -> None:
    log = _logger or logging.getLogger(__name__)
    try:
        import psutil

        for proc in psutil.process_iter(["name", "pid"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in ("ollama.exe", "ollama", "ollama app.exe"):
                    proc.terminate()
                    log.info("Ollama arrêté (PID %s)", proc.info.get("pid"))
            except Exception:
                pass
    except ImportError:
        log.warning("psutil absent — arrêt Ollama ignoré")


def _on_aria_closing() -> None:
    global _shutdown_done, _mic_active, _listen_thread
    if _shutdown_done:
        return
    _shutdown_done = True
    log = _logger or logging.getLogger(__name__)
    log.info("=== Fermeture ARIA ===")
    try:
        stt.stop_listening()
        stt._cleanup_pyaudio()
    except Exception as exc:
        log.error("Erreur arrêt STT: %s", exc)
    try:
        tts.stop()
    except Exception as exc:
        log.error("Erreur arrêt TTS: %s", exc)
    try:
        memory_engine.save_session()
        memory_engine.save_current_conversation()
        memory_engine.get_engine()._save_all()
        memory.save()
    except Exception as exc:
        log.error("Erreur sauvegarde mémoire: %s", exc)
    try:
        llamacpp_manager.stop_all_servers()
    except Exception as exc:
        log.error("Erreur arrêt llama.cpp: %s", exc)
    try:
        cfg = _config if _config else _load_config()
        if cfg.get("kill_ollama_on_exit", True):
            _stop_ollama_processes()
    except Exception as exc:
        log.error("Erreur arrêt Ollama: %s", exc)
    with _mic_lock:
        _mic_active = False
        _listen_thread = None
    log.info("=== ARIA fermé proprement ===")


def _pause_mic() -> None:
    global _mic_active, _listen_thread
    with _mic_lock:
        if not _mic_active and not stt.is_listening():
            return
        sounds.play("deactivate")
        stt.stop_listening()
        ui_bridge.set_status("idle")
        _mic_active = False
        _listen_thread = None
        ui_bridge.notify_mic_state(False)


def _resume_mic() -> None:
    global _mic_active, _listen_thread
    with _mic_lock:
        if _mic_active or stt.is_listening():
            return
        _mic_active = True
        sounds.play("activate")
        ui_bridge.set_status("listening")
        stt.start_listening()
        ui_bridge.notify_mic_state(True)


def _on_hotkey(_event=None) -> None:
    global _last_hotkey_time, _mic_active
    now = time.monotonic()
    if now - _last_hotkey_time < _HOTKEY_DEBOUNCE_S:
        return
    _last_hotkey_time = now
    stt.toggle()
    with _mic_lock:
        _mic_active = stt.is_listening()
    if _mic_active:
        sounds.play("activate")
        ui_bridge.set_status("listening")
    else:
        sounds.play("deactivate")
        ui_bridge.set_status("idle")
    ui_bridge.notify_mic_state(_mic_active)


def _start_llamacpp() -> None:
    log = _logger or logging.getLogger(__name__)
    if llamacpp_manager.should_use_ollama_gpu():
        ui_bridge.show_toast(
            "Inférence via Ollama GPU (CUDA manquant pour llama.cpp)",
            "info",
        )
        log.info("CUDA absent pour llama.cpp — inférence déléguée à Ollama GPU")
        return
    if not Path(llamacpp_manager.LLAMA_SERVER_EXE).exists():
        ui_bridge.show_toast("llama-server.exe introuvable — mode cloud API possible", "warning")
        log.warning("llama-server.exe non trouvé: %s", llamacpp_manager.LLAMA_SERVER_EXE)
        return
    available = llamacpp_manager.list_available_models()
    if not available:
        ui_bridge.show_toast("Aucun modèle GGUF trouvé", "warning")
        return
    ui_bridge.show_toast("llama.cpp démarré", "info")
    import llm

    def _start_servers() -> None:
        for role, model in (("intent", llm.MODELS["intent"]), ("fast", llm.MODELS["fast"])):
            matching = next((m for m in available if model.split(":")[0] in m), None)
            if matching:
                llamacpp_manager.start_model_server(matching)
        if llm.FORCED_MODEL:
            forced = next(
                (m for m in available if llm.FORCED_MODEL.split(":")[0] in m),
                llm.FORCED_MODEL,
            )
            if llamacpp_manager.model_exists(forced):
                llamacpp_manager.start_model_server(forced)

    threading.Thread(target=_start_servers, daemon=True).start()


def _start_static_file_server() -> None:
    import http.server
    import socket
    import socketserver

    port = 9998
    for p in range(port, port + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", p))
                port = p
                break
        except OSError:
            continue

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(app_paths.data_dir()), **kwargs)

        def log_message(self, *args):
            pass

    def _run() -> None:
        with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
            httpd.allow_reuse_address = True
            (_logger or logging.getLogger(__name__)).info(
                "Serveur statique: http://127.0.0.1:%d", port
            )
            httpd.serve_forever()

    threading.Thread(target=_run, daemon=True, name="ARIA-StaticHTTP").start()
    ui_bridge.STATIC_FILE_PORT = port


def _keyboard_thread(debug_keys: bool) -> None:
    log = logging.getLogger(__name__)
    try:
        import keyboard

        keyboard.add_hotkey("f24", _on_hotkey, suppress=False)
        keyboard.add_hotkey("ctrl+shift+a", _on_hotkey, suppress=False)
        log.info("Hooks clavier F24 + Ctrl+Shift+A enregistrés")
        keyboard.wait()
    except Exception:
        log.exception("Hook clavier indisponible")
        ui_bridge.show_error("Hook clavier impossible — vérifiez les droits admin")


@ui_bridge.expose
def shutdown() -> dict:
    _logger.info("Arrêt demandé par Electron") if _logger else None
    _on_aria_closing()
    sys.exit(0)
    return {"success": True}


def main() -> None:
    global _config, _logger
    app_paths.ensure_runtime_layout()
    _config = _load_config()
    _logger = _setup_logging(_config.get("debug", False), _config.get("log_level"))

    logging.getLogger("comtypes").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _logger.info("=== ARIA Backend démarrage ===")

    generate_sounds.ensure_sounds()
    memory.init()
    memory_engine.get_engine().update_active_hours()
    llamacpp_manager.configure(_config)
    atexit.register(llamacpp_manager.stop_all_servers)
    atexit.register(lambda: memory_engine.get_engine().save_session())
    atexit.register(lambda: memory_engine.get_engine().save_current_conversation())
    atexit.register(stt._cleanup_pyaudio)

    signal.signal(signal.SIGINT, lambda s, f: (_on_aria_closing(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (_on_aria_closing(), sys.exit(0)))

    ui_bridge.start()
    _logger.info("WebSocket serveur démarré")

    def _startup_scan() -> None:
        """Scan lancé pendant le splash screen."""
        time.sleep(1.5)
        try:
            ui_bridge.scan_apps_with_progress()
        except Exception:
            _logger.debug("Scan apps splash échoué", exc_info=True)

    threading.Thread(target=_startup_scan, daemon=True, name="ARIA-Splash-Scan").start()

    try:
        from actions.web_research import warmup_cache

        warmup_cache(
            [
                "météo Couëron",
                "actualités technologie 2026",
                "Microsoft Flight Simulator 2024",
                "aviation VFR PPL",
            ]
        )
    except Exception:
        _logger.debug("Warmup cache recherche ignoré", exc_info=True)

    time.sleep(0.5)

    def _load_llm() -> None:
        import llm  # noqa: F401
        _logger.info("Module llm chargé")

    threading.Thread(target=_load_llm, daemon=True).start()

    def _load_whisper() -> None:
        try:
            stt._load_whisper_model()
            _logger.info("Whisper prêt")
        except Exception as e:
            _logger.error("Erreur Whisper: %s", e)

    threading.Thread(target=_load_whisper, daemon=True).start()

    memory_engine.get_engine().update_active_hours()
    _logger.info("Mémoire initialisée")

    _start_static_file_server()
    threading.Thread(target=_start_llamacpp, daemon=True).start()
    threading.Thread(target=_keyboard_thread, args=(False,), daemon=True).start()

    if _config.get("mobile_auto_start", True):
        def _start_mobile() -> None:
            try:
                import aria_mobile_server as mobile_server
                mobile_server.start_mobile_server(
                    config=_config, block=False, ensure_ollama=False, banner=False
                )
                info = mobile_server.get_connect_info()
                ui_bridge.show_toast(f"📱 Mobile : {info['ip']}:{info['port']}", "info")
            except Exception:
                _logger.exception("Serveur mobile indisponible")

        threading.Thread(target=_start_mobile, daemon=True).start()

    ui_bridge.set_status("idle")
    _logger.info("=== ARIA Backend prêt ===")

    try:
        ui_bridge.apply_wake_word(_config.get("wake_word_enabled", False))
    except Exception:
        _logger.exception("Wake word init failed")

    if _config.get("light_vram_mode"):
        try:
            ui_bridge.set_light_vram_mode(True)
        except Exception:
            _logger.debug("Light VRAM mode init skipped", exc_info=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _logger.info("Arrêt manuel (Ctrl+C)")
        shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        with open(ROOT / "crash.log", "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print(f"CRASH: {e}")
        traceback.print_exc()
        sys.exit(1)
