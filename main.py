import ctypes
import sys

try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ARIA.VoiceAssistant.v2")
except Exception:
    pass

import logging
import os
import traceback
from pathlib import Path

# Répertoire du script — avant tout import projet (config.yaml, data/, etc.)
os.chdir(Path(__file__).resolve().parent)

# Logging immédiat — avant tout import de module du projet
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("assistant-vocal.log", mode="a", encoding="utf-8"),
    ],
    force=True,
)
logging.getLogger(__name__).debug("Bootstrap logging initialisé")

try:
    import ctypes
    import signal
    import threading
    import time
    import atexit
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    import keyboard
    import yaml

    import app_paths
    import briefing
    import generate_sounds
    import llm  # noqa: F401
    import memory
    import memory_engine
    import ollama_manager
    import sounds
    import stt
    import tts
    import ui

    CONFIG_PATH = app_paths.config_path()
    LOG_PATH = app_paths.app_dir() / "assistant-vocal.log"

    _mic_active = False
    _mic_lock = threading.Lock()
    _listen_thread: threading.Thread | None = None
    _config: dict = {}
    _logger: logging.Logger | None = None
    _last_hotkey_time: float = 0.0
    _HOTKEY_DEBOUNCE_S = 0.35


    def _is_admin() -> bool:
        if sys.platform != "win32":
            return True
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False


    def _setup_logging(debug: bool = False, debug_keys: bool = False) -> logging.Logger:
        level = logging.DEBUG if (debug or debug_keys) else logging.INFO
        fmt = logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s")
        root = logging.getLogger()
        root.setLevel(level)
        root.handlers.clear()

        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)

        file_handler = RotatingFileHandler(
            LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
        return logging.getLogger(__name__)


    def _load_config() -> dict:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        ollama_path = str(config["ollama_path"])
        if "USERNAME" in ollama_path:
            import os

            ollama_path = ollama_path.replace("USERNAME", os.environ.get("USERNAME", ""))
        config["ollama_path"] = Path(ollama_path)
        return config


    def _startup_checks(logger: logging.Logger, config: dict) -> None:
        if _is_admin():
            logger.info("Droits admin : OK")
        else:
            logger.warning("Droits admin : NON — le hook F24 peut ne pas fonctionner")

        logger.info("Config chargée : %s", CONFIG_PATH.name)

        try:
            import keyboard as kb  # noqa: F401
            logger.info("Bibliothèque keyboard : OK")
        except ImportError:
            logger.error("Bibliothèque keyboard non installée")

        if ollama_manager.is_running():
            logger.info("Ollama : accessible")
        else:
            logger.info("Ollama : démarrage au lancement de ARIA")

        model = config.get("model", "qwen3:14b")
        if model not in ollama_manager.get_loaded_models():
            logger.info("Modèle %s absent — pull automatique au besoin", model)
            threading.Thread(
                target=ollama_manager.pull_model, args=(model,), daemon=True
            ).start()
        else:
            logger.info("Modèle %s : présent", model)


    def _cleanup() -> None:
        global _mic_active, _listen_thread
        if _logger:
            _logger.info("Cleanup en cours…")
        memory_engine.save_session()
        memory_engine.save_current_conversation()
        memory_engine.get_engine()._save_all()
        stt.stop_listening()
        tts.stop()
        ollama_manager.stop()
        memory.save()
        ui.hide()
        with _mic_lock:
            _mic_active = False
            _listen_thread = None


    def _pause_mic() -> None:
        global _mic_active, _listen_thread
        with _mic_lock:
            if not _mic_active:
                return
            if _logger:
                _logger.info("Pause — arrêt du microphone")
            sounds.play("deactivate")
            stt.stop_listening()
            if _listen_thread is not None and _listen_thread.is_alive():
                _listen_thread.join(timeout=10)
            ui.set_status("idle")
            _mic_active = False
            _listen_thread = None


    def _resume_mic() -> None:
        global _mic_active, _listen_thread
        with _mic_lock:
            if _mic_active:
                return
            if _logger:
                _logger.info("Reprise — démarrage du microphone")
            _mic_active = True
            sounds.play("activate")
            ui.set_status("listening")
            _listen_thread = threading.Thread(target=stt.start_listening, daemon=True)
            _listen_thread.start()


    def _start_mic() -> None:
        global _mic_active, _listen_thread
        with _mic_lock:
            if _mic_active:
                return
            if _logger:
                _logger.info("Démarrage automatique du microphone")
            _mic_active = True
            ui.set_status("listening")

            if briefing.should_run_briefing():
                threading.Thread(target=briefing.run_morning_briefing, daemon=True).start()

            _listen_thread = threading.Thread(target=stt.start_listening, daemon=True)
            _listen_thread.start()


    def _toggle_mic() -> None:
        if _mic_active:
            _pause_mic()
        else:
            _resume_mic()


    def _start_ollama() -> None:
        ollama_manager.start()
        if ollama_manager.wait_until_ready(timeout=30):
            ui.show_toast("Ollama démarré")
            model = str(_config.get("model", "qwen3:14b"))
            threading.Thread(target=ollama_manager.warmup_model, args=(model,), daemon=True).start()
            threading.Thread(
                target=ollama_manager.warmup_model,
                args=(str(_config.get("model_fast", "llama3.1:8b-instruct-q8_0")),),
                daemon=True,
            ).start()
        else:
            ui.show_toast("Ollama non disponible")


    def _on_hotkey(_event=None) -> None:
        global _last_hotkey_time
        now = time.monotonic()
        if now - _last_hotkey_time < _HOTKEY_DEBOUNCE_S:
            return
        _last_hotkey_time = now

        _toggle_mic()


    def _debug_key_hook(event) -> None:
        logging.getLogger(__name__).debug(
            "Key event: %s %s", event.name, event.event_type
        )


    def _register_hotkeys(debug_keys: bool) -> None:
        logger = logging.getLogger(__name__)

        keyboard.add_hotkey("f24", _on_hotkey, suppress=False)
        logger.info("Hook add_hotkey F24 enregistré")

        keyboard.on_press_key("f24", lambda e: _on_hotkey(e), suppress=False)
        logger.info("Hook on_press_key F24 enregistré")

        keyboard.add_hotkey("ctrl+shift+a", _on_hotkey, suppress=False)
        logger.info("Hook ctrl+shift+a enregistré (raccourci test permanent)")

        if debug_keys:
            keyboard.hook(_debug_key_hook, suppress=False)
            logger.info("Debug clavier actif — chaque touche est loguée dans assistant-vocal.log")


    def _keyboard_thread(debug_keys: bool) -> None:
        logger = logging.getLogger(__name__)
        try:
            _register_hotkeys(debug_keys)
            logger.info("En attente : F24 (Copilot) ou Ctrl+Shift+A…")
            keyboard.wait()
        except Exception:
            logger.exception("Impossible d'enregistrer le hook clavier")
            ui.show_error("Hook clavier impossible — vérifiez les droits admin et PowerToys F24")


    def _signal_handler(signum, frame) -> None:
        logging.getLogger(__name__).info("Signal %s reçu", signum)
        _cleanup()
        sys.exit(0)


    def _quit_app() -> None:
        _cleanup()
        sys.exit(0)


    def main() -> None:
        global _config, _logger
        app_paths.ensure_runtime_layout()
        _config = _load_config()
        debug_keys = bool(_config.get("debug_keys", False))
        _logger = _setup_logging(_config.get("debug", False), debug_keys=debug_keys)

        generate_sounds.ensure_sounds()
        memory.init()
        memory_engine.get_engine().update_active_hours()
        ollama_manager.configure(_config["ollama_path"])

        atexit.register(lambda: memory_engine.get_engine().save_session())
        atexit.register(lambda: memory_engine.get_engine().save_current_conversation())
        atexit.register(lambda: memory_engine.get_engine()._save_all())

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        print("About to init UI...")
        ui.init(on_deactivate=_pause_mic, on_quit=_quit_app)
        print("UI init done, starting mainloop")
        ui.show()
        ui.set_status("idle")

        _startup_checks(_logger, _config)

        ollama_thread = threading.Thread(target=_start_ollama, daemon=True)
        ollama_thread.start()
        ollama_thread.join(timeout=35)

        threading.Thread(target=_keyboard_thread, args=(debug_keys,), daemon=True).start()

        def _auto_start_mic() -> None:
            time.sleep(2)
            _start_mic()

        threading.Thread(target=_auto_start_mic, daemon=True).start()

        _logger.info("Touches actives : F24 (double hook) + Ctrl+Shift+A (test)")
        _logger.info("ARIA prêt. F24 ou Ctrl+Shift+A pour mettre le micro en pause/reprise.")
        if debug_keys:
            _logger.info("debug_keys=true — consultez assistant-vocal.log pour voir les noms de touches")
        _logger.info(
            "PowerToys : assurez-vous que la touche Copilot est remappée vers F24."
        )

        ui.run()


    if __name__ == "__main__":
        main()

except Exception as e:
    try:
        with open("crash.log", "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
    except OSError:
        pass
    print(f"CRASH: {e}")
    traceback.print_exc()
    input("Appuyez sur Entrée pour fermer...")
    sys.exit(1)
