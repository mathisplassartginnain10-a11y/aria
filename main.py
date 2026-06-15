# ─── Correctif Python 3.13 : platform._wmi_query() se bloque indéfiniment ───
# Sur ce poste (Python du Microsoft Store + WMI bloqué), platform.system()/uname()
# interrogent WMI (Win32_OperatingSystem) et ne répondent jamais. pywebview appelle
# platform.system() dans guilib.initialize() → la fenêtre ne s'ouvre jamais, le micro
# semblait en cause à tort. On neutralise la branche WMI : platform retombe alors sur
# sys.getwindowsversion() + registre (rapide, fiable). DOIT s'exécuter avant tout
# import susceptible d'appeler platform.system()/uname().
import platform as _platform

_platform._wmi = None

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

    import yaml

    import app_paths
    import briefing
    import generate_sounds
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

        def _check_keyboard() -> None:
            try:
                import keyboard as kb  # noqa: F401
                logger.info("Bibliothèque keyboard : OK")
            except ImportError:
                logger.error("Bibliothèque keyboard non installée")
            except Exception as exc:
                logger.error("Bibliothèque keyboard indisponible : %s", exc)

        threading.Thread(target=_check_keyboard, daemon=True).start()

        if ollama_manager.is_running():
            logger.info("Ollama : accessible")
        else:
            logger.info("Ollama : démarrage au lancement de ARIA")
        # NB : la vérification/pull des modèles se fait dans _start_ollama,
        # APRÈS que le serveur réponde (sinon get_loaded_models() expire et
        # croit à tort que le modèle est absent → pull inutile de plusieurs Go).


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
        if not ollama_manager.wait_until_ready(timeout=60):
            ui.show_toast("Ollama non disponible")
            return
        ui.show_toast("Ollama démarré")

        # Modèles : on vérifie SEULEMENT maintenant (Ollama répond).
        loaded = ollama_manager.get_loaded_models()
        model = str(_config.get("model", "qwen3:14b"))
        if loaded and model not in loaded:
            if _logger:
                _logger.info("Modèle %s absent — pull en arrière-plan", model)
            threading.Thread(
                target=ollama_manager.pull_model, args=(model,), daemon=True
            ).start()
        elif loaded and _logger:
            _logger.info("Modèle %s : présent", model)

        # Préchauffe : modèle intent (1b) + modèle conversation rapide (8b).
        import llm

        threading.Thread(
            target=ollama_manager.warmup_model,
            args=(llm.MODELS["intent"],),
            daemon=True,
        ).start()
        threading.Thread(
            target=ollama_manager.warmup_model,
            args=(llm.MODELS["fast"],),
            daemon=True,
        ).start()

        if _config.get("wake_word_enabled", False):
            def _on_wake():
                if _logger:
                    _logger.info("Activation par wake word")
                if _mic_active:
                    _pause_mic()
                else:
                    _resume_mic()

            import wake_word

            threading.Thread(
                target=wake_word.start,
                args=(_on_wake, str(_config.get("wake_word_model", "hey_jarvis_v0.1"))),
                daemon=True,
            ).start()


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


    def _register_hotkeys(keyboard, debug_keys: bool) -> None:
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
        logger.info("Chargement du hook clavier (keyboard)…")
        try:
            import keyboard

            _register_hotkeys(keyboard, debug_keys)
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

        def _load_llm() -> None:
            import llm  # noqa: F401

            if _logger:
                _logger.info("Module llm chargé")

        threading.Thread(target=_load_llm, daemon=True).start()

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

        def _start_mobile() -> None:
            try:
                _logger.info("Démarrage serveur mobile (arrière-plan)…")
                import aria_mobile_server as mobile_server

                mobile_server.start_mobile_server(
                    config=_config, block=False, ensure_ollama=False, banner=False
                )
                info = mobile_server.get_connect_info()
                _logger.info(
                    "Serveur mobile actif — http://%s:%s (PIN config)",
                    info["ip"],
                    info["port"],
                )
                ui.show_toast(f"📱 Mobile : {info['ip']}:{info['port']}", toast_type="info")
            except Exception:
                _logger.exception("Serveur mobile indisponible")

        _logger.info("Services Ollama en arrière-plan…")
        threading.Thread(target=_start_ollama, daemon=True).start()

        if _config.get("mobile_auto_start", True):
            threading.Thread(target=_start_mobile, daemon=True).start()

        threading.Thread(target=_keyboard_thread, args=(debug_keys,), daemon=True).start()

        def _auto_start_mic() -> None:
            time.sleep(2)
            _start_mic()
            _maybe_daily_brief()

        def _maybe_daily_brief() -> None:
            try:
                import focus
                import llm

                if not _config.get("daily_brief_enabled", True):
                    return
                if focus.is_focus_active():
                    return
                if not memory_engine.should_show_daily_brief():
                    return

                def _run_brief():
                    time.sleep(3)
                    brief_text = llm.generate_daily_brief()
                    ui.append_assistant_text(brief_text)
                    ui.finalize_assistant_message()
                    tts.speak(brief_text)
                    memory_engine.mark_brief_shown()

                threading.Thread(target=_run_brief, daemon=True).start()
            except Exception:
                if _logger:
                    _logger.exception("Brief quotidien indisponible")

        threading.Thread(target=_auto_start_mic, daemon=True).start()

        _logger.info("Touches actives : F24 (double hook) + Ctrl+Shift+A (test)")
        _logger.info("ARIA prêt. F24 ou Ctrl+Shift+A pour mettre le micro en pause/reprise.")
        if debug_keys:
            _logger.info("debug_keys=true — consultez assistant-vocal.log pour voir les noms de touches")
        _logger.info(
            "PowerToys : assurez-vous que la touche Copilot est remappée vers F24."
        )
        _logger.info("Lancement fenêtre pywebview (ui.run)…")

        try:
            ui.run()
        except Exception as exc:
            _logger.error("Erreur fatale dans ui.run(): %s", exc, exc_info=True)
            traceback.print_exc()
            raise


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
