import sys
from pathlib import Path


def create() -> None:
    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")

    project_dir = Path(__file__).parent.resolve()
    python_exe = project_dir / ".venv" / "Scripts" / "python.exe"
    main_py = project_dir / "main.py"
    icon_path = project_dir / "assets" / "aria.ico"
    desktop = Path(shell.SpecialFolders("Desktop"))

    if not python_exe.exists():
        raise FileNotFoundError(f"Python venv introuvable : {python_exe}")
    if not main_py.exists():
        raise FileNotFoundError(f"main.py introuvable : {main_py}")

    old = desktop / "ARIA Assistant.lnk"
    if old.exists():
        old.unlink()

    lnk = shell.CreateShortCut(str(desktop / "ARIA Assistant.lnk"))
    lnk.TargetPath = str(python_exe)
    lnk.Arguments = f'"{main_py}"'
    lnk.WorkingDirectory = str(project_dir)
    lnk.WindowStyle = 7
    if icon_path.exists():
        lnk.IconLocation = str(icon_path)
    lnk.Description = "ARIA Voice Assistant"
    lnk.Save()
    print(f"Raccourci créé: {desktop / 'ARIA Assistant.lnk'}")
    print(f"Cible: {python_exe}")
    print(f"Arguments: \"{main_py}\"")


def main() -> None:
    try:
        create()
    except Exception as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
