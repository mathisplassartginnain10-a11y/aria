import argparse
import subprocess
import sys
from pathlib import Path


def _project_dir() -> Path:
    return Path(__file__).parent.resolve()


def _resolve_launch(use_exe: bool) -> tuple[Path, str, Path]:
    """Retourne (command, arguments, working_dir) pour la tâche planifiée."""
    working_dir = _project_dir()

    if use_exe:
        exe_path = (working_dir / "dist" / "ARIA" / "ARIA.exe").resolve()
        if not exe_path.exists():
            raise FileNotFoundError(f"ARIA.exe introuvable : {exe_path}")
        return exe_path, "", exe_path.parent

    script_path = working_dir / "main.py"
    if not script_path.exists():
        raise FileNotFoundError(f"main.py introuvable : {script_path}")

    python_exe = Path(sys.executable.replace("python.exe", "pythonw.exe"))
    if not python_exe.exists():
        python_exe = Path(sys.executable)

    return python_exe, f'"{script_path}"', working_dir


def setup_autostart(silent: bool = False, use_exe: bool = False) -> bool:
    try:
        command, arguments, exec_working_dir = _resolve_launch(use_exe)
    except FileNotFoundError as exc:
        msg = str(exc)
        if silent:
            print(msg, file=sys.stderr)
        else:
            print(msg)
        return False

    task_xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
  </Settings>
  <Actions>
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{exec_working_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

    xml_path = exec_working_dir / "autostart_task.xml"
    xml_path.write_text(task_xml, encoding="utf-16")

    result = subprocess.run(
        ["schtasks", "/create", "/tn", "AssistantVocal", "/xml", str(xml_path), "/f"],
        capture_output=True,
        text=True,
    )

    try:
        xml_path.unlink()
    except OSError:
        pass

    if result.returncode == 0:
        if not silent:
            mode = "ARIA.exe" if use_exe else "pythonw main.py"
            print("Demarrage automatique configure.")
            print("ARIA se lancera automatiquement a la prochaine connexion.")
            print(f"Tache : AssistantVocal -> {command} ({mode})")
        return True

    error_msg = (result.stderr or result.stdout or "Erreur inconnue schtasks").strip()
    if silent:
        print(f"Echec configuration demarrage automatique : {error_msg}", file=sys.stderr)
    else:
        print(f"Erreur schtasks : {error_msg}")
        print("Relancez ce script en tant qu'administrateur.")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure le demarrage automatique d'ARIA")
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Mode silencieux (utilise par install.bat, codes de sortie uniquement)",
    )
    parser.add_argument(
        "--exe",
        action="store_true",
        help="Pointe la tache planifiee vers dist/ARIA/ARIA.exe au lieu de pythonw main.py",
    )
    args = parser.parse_args()
    success = setup_autostart(silent=args.silent, use_exe=args.exe)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
