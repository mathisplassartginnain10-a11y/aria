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

USER = os.environ.get("USERNAME", "User")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", f"C:/Users/{USER}/AppData/Local")
APPDATA = os.environ.get("APPDATA", f"C:/Users/{USER}/AppData/Roaming")
PROGRAMFILES = os.environ.get("ProgramFiles", "C:/Program Files")
PROGRAMFILES86 = os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")


def _u(path: str) -> str:
    """Expand env vars and return path string."""
    return str(Path(os.path.expandvars(path)))


KNOWN_APPS: dict = {
    # === MICROSOFT FLIGHT SIMULATOR ===
    "msfs2024": [
        r"C:\Program Files\WindowsApps\Microsoft.FlightSimulator2024*\FlightSimulator2024.exe",
        r"C:\Program Files\WindowsApps\Microsoft.Limitless*\FlightSimulator2024.exe",
        _u(r"%LOCALAPPDATA%\Microsoft Flight Simulator 2024\FlightSimulator2024.exe"),
        r"shell:AppsFolder\Microsoft.FlightSimulator2024_8wekyb3d8bbwe!App",
    ],
    "msfs2020": [
        r"C:\Program Files\WindowsApps\Microsoft.FlightSimulator_*\FlightSimulator.exe",
        _u(r"%LOCALAPPDATA%\Microsoft Flight Simulator\FlightSimulator.exe"),
        r"shell:AppsFolder\Microsoft.FlightSimulator_8wekyb3d8bbwe!App",
    ],
    "msfs": "msfs2024",
    "flight simulator": "msfs2024",
    "simulateur de vol": "msfs2024",
    "fsx": [r"C:\Program Files (x86)\Steam\steamapps\common\FSX\fsx.exe"],
    # === JEUX STEAM ===
    "steam": [
        r"C:\Program Files (x86)\Steam\Steam.exe",
        r"C:\Program Files\Steam\Steam.exe",
        _u(r"%PROGRAMFILES(x86)%\Steam\Steam.exe"),
    ],
    "no mans sky": [
        r"C:\Program Files (x86)\Steam\steamapps\common\No Man's Sky\Binaries\NMS.exe",
        r"C:\Program Files\Steam\steamapps\common\No Man's Sky\Binaries\NMS.exe",
    ],
    "no man's sky": "no mans sky",
    "nms": "no mans sky",
    "age of empires 4": [
        r"C:\Program Files\WindowsApps\Xbox.AgeOfEmpires4*\RelicCardinal.exe",
        r"C:\Program Files (x86)\Steam\steamapps\common\AgeOfEmpires4\RelicCardinal.exe",
        r"shell:AppsFolder\Xbox.AgeOfEmpires4_8wekyb3d8bbwe!App",
    ],
    "aoe4": "age of empires 4",
    "age of empires": "age of empires 4",
    "cossacks 3": [
        r"C:\Program Files (x86)\Steam\steamapps\common\Cossacks 3\cossacks3.exe",
        r"C:\Program Files\Steam\steamapps\common\Cossacks 3\cossacks3.exe",
    ],
    "cossacks": "cossacks 3",
    "valorant": [
        _u(r"%LOCALAPPDATA%\Riot Games\VALORANT\live\VALORANT.exe"),
        r"C:\Riot Games\VALORANT\live\VALORANT.exe",
    ],
    "minecraft": [
        _u(r"%PROGRAMFILES(x86)%\Minecraft Launcher\MinecraftLauncher.exe"),
        _u(r"%LOCALAPPDATA%\Packages\Microsoft.MinecraftUWP_*\LocalState\games\com.mojang"),
        r"shell:AppsFolder\Microsoft.MinecraftUWP_8wekyb3d8bbwe!App",
    ],
    "fortnite": [
        _u(r"%LOCALAPPDATA%\FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe"),
        r"C:\Program Files\Epic Games\Fortnite\FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe",
    ],
    "league of legends": [
        r"C:\Riot Games\League of Legends\LeagueClient.exe",
        _u(r"%LOCALAPPDATA%\Riot Games\League of Legends\LeagueClient.exe"),
    ],
    "lol": "league of legends",
    "gta5": [
        r"C:\Program Files (x86)\Steam\steamapps\common\Grand Theft Auto V\GTA5.exe",
        r"C:\Program Files\Rockstar Games\Grand Theft Auto V\GTA5.exe",
        r"C:\Program Files\Epic Games\GTAV\GTA5.exe",
    ],
    "gta": "gta5",
    "cyberpunk": [
        r"C:\Program Files (x86)\Steam\steamapps\common\Cyberpunk 2077\bin\x64\Cyberpunk2077.exe",
        r"C:\Program Files\GOG Galaxy\Games\Cyberpunk 2077\bin\x64\Cyberpunk2077.exe",
        r"C:\Program Files\Epic Games\Cyberpunk 2077\bin\x64\Cyberpunk2077.exe",
    ],
    "elden ring": [
        r"C:\Program Files (x86)\Steam\steamapps\common\ELDEN RING\Game\eldenring.exe",
    ],
    "cs2": [
        r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe",
    ],
    "csgo": "cs2",
    "counter strike": "cs2",
    "dota 2": [
        r"C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta\game\bin\win64\dota2.exe",
    ],
    "tf2": [
        r"C:\Program Files (x86)\Steam\steamapps\common\Team Fortress 2\hl2.exe",
    ],
    "rust": [
        r"C:\Program Files (x86)\Steam\steamapps\common\Rust\RustClient.exe",
    ],
    "ark": [
        r"C:\Program Files (x86)\Steam\steamapps\common\ARK\ShooterGame\Binaries\Win64\ShooterGame.exe",
    ],
    "the witcher 3": [
        r"C:\Program Files (x86)\Steam\steamapps\common\The Witcher 3\bin\x64\witcher3.exe",
        r"C:\Program Files\GOG Galaxy\Games\The Witcher 3 Wild Hunt\bin\x64\witcher3.exe",
    ],
    "red dead": [
        r"C:\Program Files\Rockstar Games\Red Dead Redemption 2\RDR2.exe",
    ],
    "rdr2": "red dead",
    # === LAUNCHERS ===
    "epic games": [
        _u(r"%LOCALAPPDATA%\EpicGamesLauncher\Portal\Binaries\Win64\EpicGamesLauncher.exe"),
        r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
    ],
    "epic": "epic games",
    "battle net": [
        r"C:\Program Files (x86)\Battle.net\Battle.net.exe",
        r"C:\Program Files\Battle.net\Battle.net.exe",
    ],
    "battlenet": "battle net",
    "ubisoft": [
        _u(r"%LOCALAPPDATA%\Ubisoft Game Launcher\UbisoftConnect.exe"),
        r"C:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\UbisoftConnect.exe",
    ],
    "uplay": "ubisoft",
    "ea app": [
        _u(r"%LOCALAPPDATA%\Electronic Arts\EA Desktop\EA Desktop\EADesktop.exe"),
    ],
    "origin": "ea app",
    "ea": "ea app",
    "gog": [
        _u(r"%LOCALAPPDATA%\GOG.com\Galaxy\GalaxyClient.exe"),
        r"C:\Program Files (x86)\GOG Galaxy\GalaxyClient.exe",
    ],
    "rockstar": [
        _u(r"%LOCALAPPDATA%\Rockstar Games\Launcher\Launcher.exe"),
    ],
    "xbox": r"shell:AppsFolder\Microsoft.GamingApp_8wekyb3d8bbwe!Microsoft.Xbox.App",
    "xbox app": "xbox",
    # === DÉVELOPPEMENT ===
    "cursor": [
        _u(r"%LOCALAPPDATA%\Programs\cursor\Cursor.exe"),
        _u(r"%LOCALAPPDATA%\Programs\Cursor\Cursor.exe"),
        rf"C:\Users\{USER}\AppData\Local\Programs\cursor\Cursor.exe",
    ],
    "vscode": [
        _u(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
    "visual studio code": "vscode",
    "vs code": "vscode",
    "code": "vscode",
    "visual studio": [
        r"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\devenv.exe",
        r"C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\IDE\devenv.exe",
        r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\Common7\IDE\devenv.exe",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\Common7\IDE\devenv.exe",
    ],
    "git": r"C:\Program Files\Git\git-bash.exe",
    "git bash": "git",
    "github desktop": [
        _u(r"%LOCALAPPDATA%\GitHubDesktop\GitHubDesktop.exe"),
        rf"C:\Users\{USER}\AppData\Local\GitHubDesktop\GitHubDesktop.exe",
    ],
    "postman": [
        _u(r"%LOCALAPPDATA%\Postman\Postman.exe"),
    ],
    "insomnia": [
        _u(r"%LOCALAPPDATA%\insomnia\Insomnia.exe"),
    ],
    "docker": [
        r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
    ],
    "android studio": [
        r"C:\Program Files\Android\Android Studio\bin\studio64.exe",
        _u(r"%LOCALAPPDATA%\Programs\Android Studio\bin\studio64.exe"),
    ],
    "intellij": [
        r"C:\Program Files\JetBrains\IntelliJ IDEA*\bin\idea64.exe",
        _u(r"%LOCALAPPDATA%\JetBrains\IntelliJ IDEA*\bin\idea64.exe"),
    ],
    "pycharm": [
        r"C:\Program Files\JetBrains\PyCharm*\bin\pycharm64.exe",
        _u(r"%LOCALAPPDATA%\JetBrains\PyCharm*\bin\pycharm64.exe"),
    ],
    "webstorm": [
        r"C:\Program Files\JetBrains\WebStorm*\bin\webstorm64.exe",
    ],
    "sublime": [
        r"C:\Program Files\Sublime Text\sublime_text.exe",
        r"C:\Program Files\Sublime Text 3\sublime_text.exe",
    ],
    "notepad++": [
        r"C:\Program Files\Notepad++\notepad++.exe",
        r"C:\Program Files (x86)\Notepad++\notepad++.exe",
    ],
    "wsl": "wsl.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "cmd": "cmd.exe",
    "invite de commandes": "cmd.exe",
    # === NAVIGATEURS ===
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "google chrome": "chrome",
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "microsoft edge": "edge",
    "opera": [
        _u(r"%LOCALAPPDATA%\Programs\Opera GX\opera.exe"),
        _u(r"%LOCALAPPDATA%\Programs\Opera\opera.exe"),
        rf"C:\Users\{USER}\AppData\Local\Programs\Opera GX\opera.exe",
    ],
    "opera gx": "opera",
    "brave": [
        _u(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ],
    # === COMMUNICATION ===
    "discord": [
        _u(r"%LOCALAPPDATA%\Discord\app-*\Discord.exe"),
        _u(r"%LOCALAPPDATA%\Discord\Update.exe"),
        r"shell:AppsFolder\Discord.Discord_*!Discord",
    ],
    "whatsapp": [
        r"shell:AppsFolder\WhatsApp.WhatsApp_5g5c11yj14cce!WhatsApp",
        _u(r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe"),
    ],
    "telegram": [
        _u(r"%APPDATA%\Telegram Desktop\Telegram.exe"),
        _u(r"%LOCALAPPDATA%\Telegram Desktop\Telegram.exe"),
    ],
    "signal": [
        _u(r"%LOCALAPPDATA%\Programs\signal-desktop\Signal.exe"),
    ],
    "zoom": [
        _u(r"%APPDATA%\Zoom\bin\Zoom.exe"),
        _u(r"%LOCALAPPDATA%\Zoom\bin\Zoom.exe"),
    ],
    "teams": [
        _u(r"%LOCALAPPDATA%\Microsoft\Teams\Update.exe"),
        _u(r"%LOCALAPPDATA%\Microsoft\Teams\current\Teams.exe"),
        r"shell:AppsFolder\MicrosoftTeams_8wekyb3d8bbwe!MicrosoftTeams",
    ],
    "microsoft teams": "teams",
    "skype": [
        _u(r"%APPDATA%\Microsoft\Teams\current\Skype.exe"),
        r"shell:AppsFolder\Microsoft.SkypeApp_kzf8qxf38zg5c!App",
    ],
    "slack": [
        _u(r"%LOCALAPPDATA%\slack\slack.exe"),
        _u(r"%LOCALAPPDATA%\slack\app-*\slack.exe"),
    ],
    "instagram": [
        r"shell:AppsFolder\Instagram.Instagram_8xx8rvfyw5nnt!Instagram",
    ],
    # === MÉDIAS ===
    "spotify": [
        _u(r"%APPDATA%\Spotify\Spotify.exe"),
        _u(r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe"),
        r"shell:AppsFolder\SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
    ],
    "vlc": [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ],
    "media player": "wmplayer.exe",
    "windows media player": "wmplayer.exe",
    "groove": r"shell:AppsFolder\Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic",
    "films": r"shell:AppsFolder\Microsoft.ZuneVideo_8wekyb3d8bbwe!Microsoft.ZuneVideo",
    "photos": r"shell:AppsFolder\Microsoft.Windows.Photos_8wekyb3d8bbwe!App",
    # === CRÉATION ET DESIGN ===
    "obs": [
        r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
        r"C:\Program Files (x86)\obs-studio\bin\32bit\obs32.exe",
    ],
    "obs studio": "obs",
    "blender": [
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
        _u(r"%PROGRAMFILES%\Blender Foundation\Blender*\blender.exe"),
    ],
    "davinci": [
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe",
    ],
    "davinci resolve": "davinci",
    "premiere": [
        r"C:\Program Files\Adobe\Adobe Premiere Pro *\Adobe Premiere Pro.exe",
    ],
    "after effects": [
        r"C:\Program Files\Adobe\Adobe After Effects *\Support Files\AfterFX.exe",
    ],
    "photoshop": [
        r"C:\Program Files\Adobe\Adobe Photoshop *\Photoshop.exe",
    ],
    "illustrator": [
        r"C:\Program Files\Adobe\Adobe Illustrator *\Support Files\Contents\Windows\Illustrator.exe",
    ],
    "audacity": [
        r"C:\Program Files\Audacity\Audacity.exe",
        r"C:\Program Files (x86)\Audacity\Audacity.exe",
    ],
    "figma": [
        _u(r"%LOCALAPPDATA%\Figma\Figma.exe"),
    ],
    "unity": [
        r"C:\Program Files\Unity\Hub\Editor\*\Editor\Unity.exe",
        _u(r"%PROGRAMFILES%\Unity\Hub\Editor\*\Editor\Unity.exe"),
    ],
    "unity hub": [
        r"C:\Program Files\Unity Hub\Unity Hub.exe",
        _u(r"%LOCALAPPDATA%\Programs\Unity Hub\Unity Hub.exe"),
    ],
    "unreal engine": [
        r"C:\Program Files\Epic Games\UE_*\Engine\Binaries\Win64\UnrealEditor.exe",
    ],
    "unreal": "unreal engine",
    # === BUREAUTIQUE ===
    "word": [
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files\Microsoft Office 15\root\Office15\WINWORD.EXE",
    ],
    "excel": [
        r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE",
    ],
    "powerpoint": [
        r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE",
    ],
    "outlook": [
        r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE",
    ],
    "onenote": [
        r"C:\Program Files\Microsoft Office\root\Office16\ONENOTE.EXE",
        r"shell:AppsFolder\Microsoft.Office.OneNote_8wekyb3d8bbwe!microsoft.onenoteim",
    ],
    "access": [
        r"C:\Program Files\Microsoft Office\root\Office16\MSACCESS.EXE",
    ],
    "notion": [
        _u(r"%LOCALAPPDATA%\Programs\Notion\Notion.exe"),
        _u(r"%APPDATA%\Notion\Notion.exe"),
    ],
    # === OUTILS SYSTÈME ===
    "notepad": "notepad.exe",
    "bloc-notes": "notepad.exe",
    "bloc notes": "notepad.exe",
    "calculatrice": "calc.exe",
    "calculette": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "paint 3d": r"shell:AppsFolder\Microsoft.MSPaint_8wekyb3d8bbwe!Microsoft.MSPaint",
    "explorateur": "explorer.exe",
    "explorer": "explorer.exe",
    "gestionnaire de taches": "taskmgr.exe",
    "gestionnaire de tâches": "taskmgr.exe",
    "task manager": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "registre": "regedit.exe",
    "regedit": "regedit.exe",
    "gestionnaire de peripheriques": "devmgmt.msc",
    "gestionnaire de périphériques": "devmgmt.msc",
    "panneau de configuration": "control.exe",
    "parametres": "ms-settings:",
    "paramètres": "ms-settings:",
    "settings": "ms-settings:",
    "defragmentation": "dfrgui.exe",
    "nettoyage": "cleanmgr.exe",
    "moniteur de ressources": "resmon.exe",
    "performance": "perfmon.exe",
    "services": "services.msc",
    "gestion de disques": "diskmgmt.msc",
    "pare-feu": "wf.msc",
    "snip": "SnippingTool.exe",
    "capture": "SnippingTool.exe",
    "winrar": [
        r"C:\Program Files\WinRAR\WinRAR.exe",
        r"C:\Program Files (x86)\WinRAR\WinRAR.exe",
    ],
    "7zip": [
        r"C:\Program Files\7-Zip\7zFM.exe",
        r"C:\Program Files (x86)\7-Zip\7zFM.exe",
    ],
    "7-zip": "7zip",
    # === UTILITAIRES ===
    "everything": [
        r"C:\Program Files\Everything\Everything.exe",
        _u(r"%LOCALAPPDATA%\Programs\Everything\Everything.exe"),
    ],
    "powertoys": [
        r"C:\Program Files\PowerToys\PowerToys.exe",
        _u(r"%LOCALAPPDATA%\Microsoft\PowerToys\PowerToys.exe"),
    ],
    "cpu-z": [
        r"C:\Program Files\CPUID\CPU-Z\cpuz_x64.exe",
        r"C:\Program Files (x86)\CPUID\CPU-Z\cpuz.exe",
    ],
    "gpu-z": [
        _u(r"%LOCALAPPDATA%\GPU-Z\GPU-Z.exe"),
        r"C:\Program Files\GPU-Z\GPU-Z.exe",
    ],
    "hwinfo": [
        r"C:\Program Files\HWiNFO64\HWiNFO64.exe",
        r"C:\Program Files (x86)\HWiNFO32\HWiNFO32.exe",
    ],
    "msi afterburner": [
        r"C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe",
    ],
    "afterburner": "msi afterburner",
    "cinebench": [
        _u(r"%LOCALAPPDATA%\Programs\Cinebench*\Cinebench.exe"),
    ],
    "furmark": [
        r"C:\Program Files\Geeks3D\FurMark*\FurMark.exe",
        r"C:\Program Files (x86)\Geeks3D\FurMark*\FurMark.exe",
    ],
    "wireshark": [
        r"C:\Program Files\Wireshark\Wireshark.exe",
    ],
    "putty": [
        r"C:\Program Files\PuTTY\putty.exe",
        r"C:\Program Files (x86)\PuTTY\putty.exe",
    ],
    "filezilla": [
        r"C:\Program Files\FileZilla FTP Client\filezilla.exe",
        r"C:\Program Files (x86)\FileZilla FTP Client\filezilla.exe",
    ],
    "virtualbox": [
        r"C:\Program Files\Oracle\VirtualBox\VirtualBox.exe",
    ],
    "vmware": [
        r"C:\Program Files (x86)\VMware\VMware Workstation\vmware.exe",
        r"C:\Program Files\VMware\VMware Workstation\vmware.exe",
    ],
    "malwarebytes": [
        r"C:\Program Files\Malwarebytes\Anti-Malware\mbam.exe",
    ],
    "bitwarden": [
        _u(r"%LOCALAPPDATA%\Programs\bitwarden\Bitwarden.exe"),
    ],
    "veracrypt": [
        r"C:\Program Files\VeraCrypt\VeraCrypt.exe",
    ],
    "logitech": [
        _u(r"%LOCALAPPDATA%\LGHUB\lghub.exe"),
        r"C:\Program Files\LGHUB\lghub.exe",
    ],
    "lghub": "logitech",
    "geforce experience": [
        r"C:\Program Files\NVIDIA Corporation\NVIDIA GeForce Experience\NVIDIA GeForce Experience.exe",
    ],
    "nvidia": "geforce experience",
    "amd radeon": [
        r"C:\Program Files\AMD\CNext\CNext\RadeonSoftware.exe",
    ],
    "radeon": "amd radeon",
    # === AVIATION ===
    "sayintentions": [
        _u(r"%LOCALAPPDATA%\Programs\SayIntentions.AI\SayIntentions.exe"),
        _u(r"%APPDATA%\SayIntentions.AI\SayIntentions.exe"),
        rf"C:\Users\{USER}\AppData\Local\Programs\SayIntentions.AI\SayIntentions.exe",
    ],
    "say intentions": "sayintentions",
    "littlenavmap": [
        _u(r"%LOCALAPPDATA%\Programs\Little Navmap\littlenavmap.exe"),
        r"C:\Little Navmap\littlenavmap.exe",
    ],
    "little navmap": "littlenavmap",
    "pfpx": [
        r"C:\Program Files (x86)\PFPX\PFPX.exe",
    ],
    "simbrief": "chrome",
    # === MUSIQUE ===
    "itunes": [
        r"C:\Program Files\iTunes\iTunes.exe",
        r"C:\Program Files (x86)\iTunes\iTunes.exe",
        r"shell:AppsFolder\AppleInc.iTunes_nzyj5cx40ttqa!iTunes",
    ],
    "deezer": [
        _u(r"%LOCALAPPDATA%\Programs\Deezer\Deezer.exe"),
        r"shell:AppsFolder\Deezer.Deezer_*!App",
    ],
    "tidal": [
        _u(r"%LOCALAPPDATA%\TIDAL\TIDAL.exe"),
    ],
    # === MICROSOFT STORE APPS ===
    "netflix": r"shell:AppsFolder\4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix",
    "tiktok": r"shell:AppsFolder\TikTok.TikTok_ywdps6kjntwvw!TikTok",
    "store": r"shell:AppsFolder\Microsoft.WindowsStore_8wekyb3d8bbwe!App",
    "windows store": "store",
    "xbox game bar": r"shell:AppsFolder\Microsoft.XboxGamingOverlay_8wekyb3d8bbwe!App",
    "cortana": r"shell:AppsFolder\Microsoft.549981C3F5F10_8wekyb3d8bbwe!App",
    "mail": r"shell:AppsFolder\microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowsLive.mail",
    "calendrier": r"shell:AppsFolder\microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowsLive.calendar",
    "meteo": r"shell:AppsFolder\Microsoft.BingWeather_8wekyb3d8bbwe!App",
    "actualites": r"shell:AppsFolder\Microsoft.BingNews_8wekyb3d8bbwe!AppexNews",
    "cartes": r"shell:AppsFolder\Microsoft.WindowsMaps_8wekyb3d8bbwe!App",
    "camera": r"shell:AppsFolder\Microsoft.WindowsCamera_8wekyb3d8bbwe!App",
    "horloge": r"shell:AppsFolder\Microsoft.WindowsAlarms_8wekyb3d8bbwe!App",
    "alarme": "horloge",
}

CLOSE_ALIASES: dict[str, str] = {
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "spotify": "Spotify.exe",
    "discord": "Discord.exe",
    "steam": "steam.exe",
    "msfs": "FlightSimulator2024.exe",
    "msfs2024": "FlightSimulator2024.exe",
    "msfs2020": "FlightSimulator.exe",
    "flight simulator": "FlightSimulator2024.exe",
    "simulateur de vol": "FlightSimulator2024.exe",
    "firefox": "firefox.exe",
    "opera": "opera.exe",
    "opera gx": "opera.exe",
    "vscode": "Code.exe",
    "visual studio code": "Code.exe",
    "cursor": "Cursor.exe",
    "obs": "obs64.exe",
    "obs studio": "obs64.exe",
    "teams": "Teams.exe",
    "slack": "slack.exe",
    "valorant": "VALORANT.exe",
    "league of legends": "LeagueClient.exe",
    "lol": "LeagueClient.exe",
}


def _load_custom_apps() -> None:
    try:
        with app_paths.config_path().open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        for key, path in config.get("apps", {}).items():
            KNOWN_APPS[key.lower()] = str(path)
    except Exception:
        logger.debug("Custom apps non chargés", exc_info=True)


_load_custom_apps()


def _resolve_path_candidate(path: str) -> str | None:
    """Résout un candidat (glob, shell URI, chemin absolu ou exe PATH)."""
    if path.startswith("shell:"):
        return path
    expanded = os.path.expandvars(path)
    if "*" in expanded:
        matches = sorted(glob.glob(expanded))
        return matches[-1] if matches else None
    if os.path.exists(expanded):
        return expanded
    if os.path.sep not in expanded and (not os.path.altsep or os.path.altsep not in expanded):
        return expanded
    return None


def _resolve_app(name: str) -> str | None:
    """Résout un nom d'app en chemin exécutable, avec gestion des aliases."""
    val = KNOWN_APPS.get(name.lower().strip())
    if val is None:
        return None
    if isinstance(val, str) and val in KNOWN_APPS:
        return _resolve_app(val)
    if isinstance(val, str):
        return _resolve_path_candidate(val)
    if isinstance(val, list):
        for path in val:
            resolved = _resolve_path_candidate(path)
            if resolved:
                return resolved
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
    if (
        os.path.sep not in target
        and (not os.path.altsep or os.path.altsep not in target)
        and target.endswith(".exe")
    ):
        return True
    if target.endswith(".msc") or target.endswith(".cpl"):
        return True
    return os.path.exists(target)


def _resolve_launch_target(name_lower: str) -> str | None:
    _load_custom_apps()

    path = _resolve_app(name_lower)
    if not path:
        for key in KNOWN_APPS:
            if key in name_lower or name_lower in key:
                path = _resolve_app(key)
                if path:
                    break

    if not path:
        path = (
            _find_in_registry(name_lower.replace(" ", ""))
            or _search_start_menu(name_lower)
            or _search_everywhere(name_lower)
        )

    if path and _target_is_launchable(path):
        return path
    return None


def _resolve_app_target(name_lower: str) -> str | None:
    """Compatibilité fermeture / focus."""
    return _resolve_launch_target(name_lower)


def _execute_launch(path: str, label: str) -> str:
    """Lance un path résolu."""
    try:
        if path.startswith("shell:"):
            subprocess.Popen(
                f'explorer.exe "{path}"',
                shell=True,
                creationflags=CREATE_NO_WINDOW,
            )
        elif path.endswith(".msc") or path.endswith(".cpl"):
            subprocess.Popen(["mmc.exe", path], creationflags=CREATE_NO_WINDOW)
        elif path.endswith(":"):
            os.startfile(path)
        elif path.endswith(".lnk"):
            os.startfile(path)
        else:
            subprocess.Popen([path], creationflags=CREATE_NO_WINDOW)
        logger.info("Lancé: %s → %s", label, path)
        memory.remember("context.last_app_launched", label)
        return f"{label} lancé"
    except FileNotFoundError:
        return f"Fichier introuvable : {path}"
    except Exception as exc:
        logger.error("Erreur lancement %s: %s", label, exc)
        return f"Erreur : {exc}"


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
    """Lance une application. Cherche dans KNOWN_APPS puis fallback."""
    name_lower = app_name.lower().strip()
    name_lower = re.sub(
        r"^(lance(?:-moi)?|ouvre(?:-moi)?|d[ée]marre(?:-moi)?|mets?)\s+",
        "",
        name_lower,
        flags=re.I,
    ).strip()
    name_lower = re.sub(r"\s+en route$", "", name_lower).strip()

    path = _resolve_launch_target(name_lower)
    if not path:
        return f"Application '{app_name}' introuvable sur ce PC"

    return _execute_launch(path, app_name.strip())


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
        if isinstance(val, str):
            if val.endswith(".exe"):
                known_exes.add(Path(val).name.lower())
            elif val in KNOWN_APPS:
                nested = KNOWN_APPS[val]
                if isinstance(nested, str) and nested.endswith(".exe"):
                    known_exes.add(Path(nested).name.lower())
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
