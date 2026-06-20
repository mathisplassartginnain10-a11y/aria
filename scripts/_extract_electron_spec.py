"""Extract Electron files from aria-spec-v19-electron.md."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = (ROOT / "docs" / "aria-spec-v19-electron.md").read_text(encoding="utf-8")
base = ROOT / "electron"
base.mkdir(exist_ok=True)
(base / "renderer").mkdir(exist_ok=True)
(base / "assets").mkdir(exist_ok=True)


def extract(start_marker: str, end_marker: str | None = None) -> str:
    i = spec.find(start_marker)
    if i < 0:
        raise SystemExit(f"marker not found: {start_marker}")
    i = spec.find("```", i)
    i = spec.find("\n", i) + 1
    if end_marker:
        j = spec.find(end_marker, i)
        block = spec[i:j]
        j2 = block.rfind("```")
        return block[:j2] if j2 >= 0 else block
    j = spec.find("```", i)
    return spec[i:j]


main = extract("## FICHIER 2 — electron/main.js", "## FICHIER 3")
main = main.replace(
    "path.join(__dirname, '..', 'python', '.venv', 'Scripts', 'python.exe')",
    "path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe')",
)
main = main.replace(
    "path.join(__dirname, '..', 'python', '.venv', 'bin', 'python3')",
    "path.join(__dirname, '..', '.venv', 'bin', 'python3')",
)
main = main.replace(
    "cwd: path.join(__dirname, '..', 'python'),",
    "cwd: path.join(__dirname, '..'),",
)
ipc = """
// Contrôles de fenêtre
ipcMain.on('window-minimize', () => { if (mainWindow) mainWindow.minimize(); });
ipcMain.on('window-maximize', () => {
  if (mainWindow) {
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
  }
});
ipcMain.on('window-close', () => { if (mainWindow) mainWindow.close(); });
"""
main = main.replace(
    "ipcMain.on('quit-app', () => {\n  app.quit();\n});",
    "ipcMain.on('quit-app', () => {\n  app.quit();\n});" + ipc,
)
(base / "main.js").write_text(main, encoding="utf-8")

(base / "preload.js").write_text(
    extract("## FICHIER 3 — electron/preload.js", "## FICHIER 4"), encoding="utf-8"
)
(base / "package.json").write_text(
    extract("## FICHIER 4 — electron/package.json", "## FICHIER 5"), encoding="utf-8"
)
(base / "renderer" / "index.html").write_text(
    extract("## FICHIER 5 — electron/renderer/index.html", "## FICHIER 6"), encoding="utf-8"
)

app = extract("## FICHIER 6 — electron/renderer/app.js", "## FICHIER 7")
if "tts_finished" not in app:
    app = app.replace(
        "  api.on('assistant_done', () => finalizeAssistantMessage());\n}",
        "  api.on('assistant_done', () => finalizeAssistantMessage());\n\n"
        "  api.on('tts_finished', () => {\n"
        "    if (state.micActive) setStatus('listening');\n"
        "    else setStatus('idle');\n"
        "  });\n}",
    )
(base / "renderer" / "app.js").write_text(app, encoding="utf-8")

css = extract("## FICHIER 7 — electron/renderer/styles.css", "## FICHIER 8")
(base / "renderer" / "styles.css").write_text(css, encoding="utf-8")

print("OK:", (base / "main.js").stat().st_size, "bytes main.js")
