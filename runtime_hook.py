"""Runtime hook PyInstaller — initialisation des chemins ARIA."""

import app_paths

app_paths.ensure_runtime_layout()
