"""
Réduit site_aliases.db sous une limite de taille.

Supprime la base gonflée (+ WAL) et reconstruit depuis le catalogue de base
(~28 000 entrées), puis ré-applique des doublements SQL tant que la taille
reste sous la limite.

Usage:
    python scripts/shrink_aliases_db.py
    python scripts/shrink_aliases_db.py --max-gb 20
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Réduit la base alias sites")
    parser.add_argument("--max-gb", type=float, default=20.0)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    from actions.alias_store import DB_PATH, shrink_db, _merge_base

    data = DB_PATH.parent
    before_gb = 0.0
    for name in os.listdir(data):
        if name.startswith("site_aliases"):
            before_gb += os.path.getsize(data / name) / 1e9

    print(f"Catalogue de base : {len(_merge_base()):,} entrées", flush=True)
    print(f"Taille actuelle   : {before_gb:.1f} Go (db + wal + shm)", flush=True)
    print(f"Limite cible      : {args.max_gb:.0f} Go", flush=True)
    print("Suppression et reconstruction…", flush=True)

    t0 = time.perf_counter()
    total = shrink_db(max_gb=args.max_gb)
    elapsed = time.perf_counter() - t0

    after_gb = DB_PATH.stat().st_size / 1e9 if DB_PATH.exists() else 0.0
    wal = Path(str(DB_PATH) + "-wal")
    if wal.exists():
        after_gb += wal.stat().st_size / 1e9

    stub = ROOT / "actions" / "site_aliases_extra.py"
    stub.write_text(
        "# Auto-generated — alias stockés dans data/site_aliases.db\n"
        "from __future__ import annotations\n\n"
        f"ALIAS_COUNT = {total}\n"
        "_ALIASES_EXTRA: dict[str, str] = {}  # voir actions/alias_store.py\n",
        encoding="utf-8",
    )

    import shutil

    free_gb = shutil.disk_usage(data).free / 1e9
    print(f"Terminé en {elapsed:.1f}s", flush=True)
    print(f"  entrées  : {total:,}", flush=True)
    print(f"  taille   : {after_gb:.2f} Go", flush=True)
    print(f"  libéré   : {max(0, before_gb - after_gb):.1f} Go", flush=True)
    print(f"  libre C: : {free_gb:.1f} Go", flush=True)


if __name__ == "__main__":
    main()
