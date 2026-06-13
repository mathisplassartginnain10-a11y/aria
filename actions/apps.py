import glob
import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import psutil
import yaml

import app_paths
import memory

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

KNOWN_APPS: dict = {
    "msfs": [
        r"C:\Program Files\WindowsApps\Microsoft.FlightSimulator*\FlightSimulator.exe",
        r"C:\Program Files (x86)\Steam\steamapps\common\MicrosoftFlightSimulator\FlightSimulator.exe",
    ],
    "flight simulator": "msfs",
    "simulateur de vol": "msfs",
    "steam": r"C:\Program Files (x86)\Steam\Steam.exe",
    "valorant": r"C:\Riot Games\VALORANT\live\VALORANT.exe",
    "no man sky": r"C:\Program Files (x86)\Steam\steamapps\common\No Man's Sky\Binaries\NMS.exe",
    "no man's sky": r"C:\Program Files (x86)\Steam\steamapps\common\No Man's Sky\Binaries\NMS.exe",
    "age of empires": r"C:\Program Files\WindowsApps\Microsoft.MSPhoenix*\RelicCardinal.exe",
    "cossacks": r"C:\Program Files (x86)\Steam\steamapps\common\Cossacks 3\cossacks3.exe",
    "cursor": [
        r"C:\Users\mathi\AppData\Local\Programs\cursor\Cursor.exe",
        r"C:\Users\%USERNAME%\AppData\Local\Programs\cursor\Cursor.exe",
    ],
    "vscode": [
        r"C:\Users\mathi\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
    "visual studio code": "vscode",
    "code": "vscode",
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "opera": r"C:\Users\mathi\AppData\Local\Programs\Opera GX\opera.exe",
    "opera gx": r"C:\Users\mathi\AppData\Local\Programs\Opera GX\opera.exe",
    "discord": r"C:\Users\mathi\AppData\Local\Discord\app-*\Discord.exe",
    "spotify": r"C:\Users\mathi\AppData\Roaming\Spotify\Spotify.exe",
    "vlc": r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    "obs": r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
    "notepad": "notepad.exe",
    "bloc-notes": "notepad.exe",
    "calculatrice": "calc.exe",
    "calculette": "calc.exe",
    "calc": "calc.exe",
    "explorateur": "explorer.exe",
    "explorer": "explorer.exe",
    "gestionnaire de tâches": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "paint": "mspaint.exe",
    "word": r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
    "excel": r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
    "blender": r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
    "unity": r"C:\Program Files\Unity\Hub\Editor\*\Editor\Unity.exe",
    "paramètres": "ms-settings:",
    "parametres": "ms-settings:",
    "store": "ms-windows-store:",
    "xbox": "xbox:",
    # Alias noms → exe (fermeture fiable)
    "microsoft edge": "msedge.exe",
    "google chrome": "chrome.exe",
}

CLOSE_ALIASES: dict[str, str] = {
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "spotify": "Spotify.exe",
    "discord": "Discord.exe",
    "steam": "steam.exe",
    "msfs": "FlightSimulator.exe",
    "flight simulator": "FlightSimulator.exe",
    "simulateur de vol": "FlightSimulator.exe",
}

UWP_APPS: dict[str, str] = {
    "whatsapp": "WhatsApp",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "netflix": "Netflix",
}


def _match_uwp_app(name_lower: str) -> str | None:
    for key, package_name in UWP_APPS.items():
        if key in name_lower or name_lower in key:
            return package_name
    return None


def _launch_uwp(app_name: str) -> bool:
    try:
        subprocess.Popen(
            [
                "powershell",
                "-WindowStyle",
                "Hidden",
                "-Command",
                f'Start-Process "shell:AppsFolder\\$(Get-AppxPackage *{app_name}* | Select-Object -First 1 | ForEach-Object {{$_.PackageFamilyName + "!App"}})"',
            ],
            creationflags=CREATE_NO_WINDOW,
        )
        return True
    except Exception as exc:
        logger.error("UWP launch error: %s", exc)
        return False


def _load_custom_apps() -> None:
    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        for key, path in config.get("apps", {}).items():
            KNOWN_APPS[key.lower()] = str(path)
    except Exception:
        logger.debug("Custom apps non chargés", exc_info=True)


_load_custom_apps()


def _resolve_path(path_str: str) -> str | None:
    if not path_str or path_str.endswith(":"):
        return path_str

    path_str = os.path.expandvars(path_str)

    if "*" in path_str:
        matches = sorted(glob.glob(path_str))
        if matches:
            return matches[-1]
        return None

    if os.path.exists(path_str):
        return path_str

    return None


def _find_in_registry(app_name: str) -> str | None:
    try:
        import winreg

        keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths",
        ]
        candidates = [
            f"{app_name}.exe",
            app_name if app_name.endswith(".exe") else f"{app_name}.exe",
        ]
        for key_path in keys:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                for candidate in candidates:
                    try:
                        subkey = winreg.OpenKey(key, candidate)
                        val, _ = winreg.QueryValueEx(subkey, "")
                        if val and os.path.exists(val):
                            return val
                    except FileNotFoundError:
                        pass
            except OSError:
                pass
    except Exception:
        logger.debug("Registry search failed", exc_info=True)
    return None


def _search_start_menu(app_name: str) -> str | None:
    try:
        start_dirs = [
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
        ]
        for start_dir in start_dirs:
            if not os.path.isdir(start_dir):
                continue
            for root, _dirs, files in os.walk(start_dir):
                for filename in files:
                    if filename.lower().endswith(".lnk") and app_name.lower() in filename.lower():
                        return os.path.join(root, filename)
    except Exception:
        logger.debug("Start menu search failed", exc_info=True)
    return None


def _search_everywhere(app_name: str) -> str | None:
    """Cherche une app partout sur le système."""
    import winreg

    name_lower = app_name.lower()

    store_dirs = [
        r"C:\Program Files\WindowsApps",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps"),
    ]
    for store_dir in store_dirs:
        try:
            for folder in os.listdir(store_dir):
                if name_lower.replace(" ", "") in folder.lower().replace(" ", ""):
                    for exe in glob.glob(os.path.join(store_dir, folder, "*.exe")):
                        return exe
        except Exception:
            pass

    uninstall_keys = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for key_path in uninstall_keys:
            try:
                key = winreg.OpenKey(hive, key_path)
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        subkey = winreg.OpenKey(key, subkey_name)
                        try:
                            display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                            if name_lower in display_name.lower():
                                try:
                                    install_loc, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                                    if install_loc:
                                        exes = glob.glob(os.path.join(install_loc, "*.exe"))
                                        if exes:
                                            return exes[0]
                                except FileNotFoundError:
                                    pass
                        except FileNotFoundError:
                            pass
                    except Exception:
                        pass
            except Exception:
                pass

    uwp_apps = {
        "spotify": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
        "xbox": "Microsoft.XboxApp_8wekyb3d8bbwe!Microsoft.XboxApp",
        "photos": "Microsoft.Windows.Photos_8wekyb3d8bbwe!App",
        "calculatrice": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
        "store": "Microsoft.WindowsStore_8wekyb3d8bbwe!App",
    }
    for key, app_id in uwp_apps.items():
        if key in name_lower or name_lower in key:
            return f"shell:AppsFolder\\{app_id}"

    search_dirs = [
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
        os.path.expandvars(r"%APPDATA%"),
    ]
    for search_dir in search_dirs:
        try:
            for root, dirs, files in os.walk(search_dir):
                depth = root.replace(search_dir, "").count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                for f in files:
                    if f.lower().endswith(".exe") and name_lower in f.lower().replace(".exe", ""):
                        return os.path.join(root, f)
        except Exception:
            pass

    return None


def _target_is_launchable(target: str) -> bool:
    if target.startswith("shell:") or target.endswith(":"):
        return True
    if target.endswith(".lnk"):
        return os.path.exists(target)
    if (os.path.sep not in target and (not os.path.altsep or os.path.altsep not in target)) and target.endswith(".exe"):
        return True
    return os.path.exists(target)


def _resolve_app_target(name_lower: str) -> str | None:
    _load_custom_apps()
    target = None

    for key, value in KNOWN_APPS.items():
        if key in name_lower or name_lower in key:
            if isinstance(value, str) and value in KNOWN_APPS and not value.endswith((".exe", ":")):
                value = KNOWN_APPS[value]
            if isinstance(value, list):
                for entry in value:
                    resolved = _resolve_path(entry)
                    if resolved:
                        target = resolved
                        break
            elif isinstance(value, str):
                if value in KNOWN_APPS:
                    nested = KNOWN_APPS[value]
                    if isinstance(nested, list):
                        for entry in nested:
                            resolved = _resolve_path(entry)
                            if resolved:
                                target = resolved
                                break
                    elif isinstance(nested, str):
                        target = _resolve_path(nested) or nested
                else:
                    target = _resolve_path(value) if ("*" in value or "%" in value) else value
            if target:
                break

    if target and isinstance(target, str) and not target.endswith(":") and not target.startswith("shell:") and not os.path.exists(target):
        if "*" in target or "%" in target:
            target = _resolve_path(target)

    if not target or (
        isinstance(target, str)
        and not target.endswith(":")
        and not target.startswith("shell:")
        and not os.path.exists(target)
    ):
        reg_path = _find_in_registry(name_lower.replace(" ", ""))
        if reg_path:
            target = reg_path

    if not target:
        lnk = _search_start_menu(name_lower)
        if lnk:
            target = lnk

    return target


def _normalize_close_query(app_name: str) -> str:
    name_lower = app_name.lower().strip()
    name_lower = re.sub(
        r"^(ferme(?:-moi)?|quitte(?:-moi)?|arr[êe]te(?:-moi)?|stop)\s+",
        "",
        name_lower,
        flags=re.I,
    ).strip()
    for word in ("ferme", "quitte", "arrête", "arrete", "stop", "fermer", "moi"):
        name_lower = re.sub(rf"\b{word}\b", "", name_lower).strip()
    name_lower = re.sub(r"\s+", " ", name_lower).strip()
    return name_lower


def _resolve_close_process_names(name_lower: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if not name:
            return
        key = name.lower()
        if key not in seen:
            seen.add(key)
            candidates.append(key)

    for alias, exe in CLOSE_ALIASES.items():
        if alias == name_lower or alias in name_lower or name_lower in alias:
            add(exe)

    target = _resolve_app_target(name_lower)
    if target:
        if isinstance(target, str):
            if target.endswith(".lnk"):
                add(f"{Path(target).stem}.exe")
            elif target.lower().endswith(".exe"):
                add(Path(target).name)
            elif not target.endswith(":"):
                add(Path(target).name)

    compact = name_lower.replace(" ", "")
    add(compact if compact.endswith(".exe") else f"{compact}.exe")
    add(name_lower.replace(" ", ""))

    return candidates


def _process_matches_close(proc_name: str, candidates: list[str], name_lower: str) -> bool:
    proc_lower = (proc_name or "").lower()
    if not proc_lower:
        return False
    proc_stem = proc_lower[:-4] if proc_lower.endswith(".exe") else proc_lower

    for candidate in candidates:
        cand = candidate.lower()
        cand_stem = cand[:-4] if cand.endswith(".exe") else cand
        if proc_lower == cand or proc_stem == cand_stem:
            return True

    query_stem = name_lower.replace(" ", "")
    if len(query_stem) >= 3 and (query_stem in proc_stem or proc_stem in query_stem):
        return True
    return False


def launch(app_name: str) -> str:
    name_lower = app_name.lower().strip()
    name_lower = re.sub(
        r"^(lance(?:-moi)?|ouvre(?:-moi)?|d[ée]marre(?:-moi)?|mets?)\s+",
        "",
        name_lower,
        flags=re.I,
    ).strip()
    name_lower = re.sub(r"\s+en route$", "", name_lower).strip()

    uwp_package = _match_uwp_app(name_lower)
    if uwp_package:
        if _launch_uwp(uwp_package):
            logger.info("Lancé via UWP: %s", uwp_package)
            memory.remember("context.last_app_launched", app_name)
            return f"{app_name} ouvert"
        return f"Je n'ai pas pu lancer {app_name}"

    target = _resolve_app_target(name_lower)
    if not target or (isinstance(target, str) and not _target_is_launchable(target)):
        found = _search_everywhere(name_lower)
        if found:
            target = found

    if not target:
        return f"Je n'ai pas trouvé {app_name} sur ton PC"

    try:
        if isinstance(target, str) and target.startswith("shell:"):
            subprocess.Popen(
                f'explorer.exe "{target}"',
                shell=True,
                creationflags=CREATE_NO_WINDOW,
            )
            logger.info("Lancé via shell: %s", target)
            memory.remember("context.last_app_launched", app_name)
            return f"{app_name} ouvert"
        if isinstance(target, str) and target.endswith(":"):
            os.startfile(target)
            logger.info("Lancé via URI: %s", target)
            memory.remember("context.last_app_launched", app_name)
            return f"{app_name} ouvert"
        if isinstance(target, str) and target.endswith(".lnk"):
            os.startfile(target)
            logger.info("Lancé via raccourci: %s", target)
            memory.remember("context.last_app_launched", app_name)
            return f"{app_name} lancé"
        subprocess.Popen(
            [target],
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
        )
        logger.info("Lancé: %s", target)
        memory.remember("context.last_app_launched", app_name)
        return f"{app_name} lancé"
    except FileNotFoundError:
        logger.error("App introuvable: %s (résolu: %s)", app_name, target)
        return f"Je n'ai pas trouvé {app_name} sur ton PC"
    except Exception as exc:
        logger.error("Erreur lancement %s: %s", app_name, exc)
        return f"Erreur au lancement de {app_name}: {exc}"


def launch_multiple(app_names: list[str]) -> str:
    """Lance plusieurs apps en parallèle."""
    if not app_names:
        return "Aucune app à lancer"

    results: list[str] = []
    threads: list[threading.Thread] = []
    lock = threading.Lock()

    def _launch_one(name: str) -> None:
        result = launch(name)
        with lock:
            results.append(result)

    for name in app_names:
        t = threading.Thread(target=_launch_one, args=(name,), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=10)

    return ", ".join(results)


def close(app_name: str) -> str:
    name_lower = _normalize_close_query(app_name)
    if not name_lower:
        return "Quelle application veux-tu fermer ?"

    candidates = _resolve_close_process_names(name_lower)
    targets: list[psutil.Process] = []
    closed_names: list[str] = []

    for proc in psutil.process_iter(["name", "pid"]):
        try:
            proc_name = proc.info.get("name") or ""
            if _process_matches_close(proc_name, candidates, name_lower):
                targets.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    seen_pids: set[int] = set()
    for proc in targets:
        try:
            pid = proc.pid
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
            proc.terminate()
            closed_names.append(proc.name())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if targets:
        _gone, alive = psutil.wait_procs(targets, timeout=3)
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    if closed_names:
        unique = sorted(set(closed_names))
        return f"{', '.join(unique)} fermé(s)"
    return f"Aucun processus trouvé pour {app_name.strip()}"


def close_all_except(keep_list: list[str]) -> str:
    keep_lower = [k.lower() for k in keep_list]
    closed = 0
    for key in list(KNOWN_APPS.keys()):
        if key in keep_lower:
            continue
        result = close(key)
        if "fermé" in result.lower():
            closed += 1
    return f"{closed} applications fermées."


def list_running() -> list[str]:
    running: list[str] = []
    known_exes: set[str] = set()
    for val in KNOWN_APPS.values():
        if isinstance(val, str) and val.endswith(".exe"):
            known_exes.add(Path(val).name.lower())
        elif isinstance(val, list):
            for entry in val:
                if isinstance(entry, str) and entry.endswith(".exe"):
                    known_exes.add(Path(entry).name.lower())

    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name in known_exes:
                running.append(proc.info["name"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return list(set(running))


def focus(app_name: str) -> str:
    try:
        import pygetwindow as gw

        windows = gw.getWindowsWithTitle(app_name)
        if windows:
            windows[0].activate()
            return f"{app_name} mis au premier plan"
    except Exception as exc:
        logger.error("Focus error: %s", exc)
    return f"Impossible de mettre {app_name} au premier plan"
