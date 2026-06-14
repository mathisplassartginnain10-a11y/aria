"""
Double le catalogue de sites connus.

Chaque exécution = un nouveau batch (variantes vocales sur tout le catalogue).
Préfixes alternés : open → ouvrir → go to → va sur → lance → visite → site → …

Usage:
    python scripts/double_sites.py
    python scripts/double_sites.py --repeat 5
    python scripts/shrink_aliases_db.py --max-gb 20
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
MAX_DB_GB = 20.0


def _batch_numbers() -> list[int]:
    import re

    return sorted(
        int(m.group(1))
        for p in SCRIPTS.glob("aliases_batch*.py")
        if (m := re.fullmatch(r"aliases_batch(\d+)", p.stem))
    )


def _write_marker_batch(batch_num: int, prefix: str) -> Path:
    out = SCRIPTS / f"aliases_batch{batch_num}.py"
    out.write_text(
        f'"""Batch {batch_num} — préfixe « {prefix} » (appliqué via SQLite)."""\n'
        f'PREFIX = "{prefix}"\n'
        f"SQL_DOUBLED = True\n\n\n"
        f"def get_batch{batch_num}() -> dict[str, str]:\n"
        f'    return {{}}\n',
        encoding="utf-8",
    )
    return out


def _update_stub(total: int) -> None:
    out = ROOT / "actions" / "site_aliases_extra.py"
    out.write_text(
        "# Auto-generated — alias stockés dans data/site_aliases.db\n"
        "from __future__ import annotations\n\n"
        f"ALIAS_COUNT = {total}\n"
        "_ALIASES_EXTRA: dict[str, str] = {}  # voir actions/alias_store.py\n",
        encoding="utf-8",
    )


def _require_disk_space() -> None:
    data = ROOT / "data"
    db = data / "site_aliases.db"
    free_gb = shutil.disk_usage(data).free / 1e9
    need_gb = 2.0
    if db.exists():
        need_gb = max(2.0, db.stat().st_size / 1e9 * 1.05)
    print(f"  Espace disque: {free_gb:.1f} Go libres (~{need_gb:.0f} Go requis)", flush=True)
    if free_gb < need_gb:
        print(f"Arrêt: espace insuffisant ({free_gb:.1f} Go libres).", flush=True)
        sys.exit(1)


def _require_db_under_limit() -> None:
    db = ROOT / "data" / "site_aliases.db"
    if not db.exists():
        return
    size_gb = db.stat().st_size / 1e9
    wal = Path(str(db) + "-wal")
    if wal.exists():
        size_gb += wal.stat().st_size / 1e9
    if size_gb >= MAX_DB_GB:
        print(
            f"Arrêt: base {size_gb:.1f} Go >= limite {MAX_DB_GB:.0f} Go. "
            f"Lancez: python scripts/shrink_aliases_db.py --max-gb {MAX_DB_GB:.0f}",
            flush=True,
        )
        sys.exit(1)


def double_once() -> tuple[int, int, int, str]:
    sys.path.insert(0, str(ROOT))
    from actions.alias_store import (
        _db_is_large,
        apply_prefix_and_record,
        fast_count,
        prefix_for_batch,
        raw_count,
    )

    nums = _batch_numbers()
    sql_batches = [n for n in nums if n >= 8]
    next_num = (max(nums) + 1) if nums else 7
    prefix = prefix_for_batch(next_num)

    recorded = ROOT / "data" / "site_aliases_prefixes.txt"
    applied: list[str] = []
    if recorded.exists():
        applied = [
            line.strip()
            for line in recorded.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    last_batch = SCRIPTS / f"aliases_batch{nums[-1]}.py" if nums else None
    if last_batch and last_batch.exists() and sql_batches:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            f"aliases_batch{nums[-1]}", last_batch
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if getattr(mod, "SQL_DOUBLED", False) and len(applied) < len(sql_batches):
            next_num = nums[-1]
            prefix = getattr(mod, "PREFIX", prefix_for_batch(next_num))
            print(
                f"Reprise batch {next_num} — préfixe « {prefix} » "
                f"({len(applied)}/{len(sql_batches)} enregistrés)",
                flush=True,
            )

    if _db_is_large():
        before = fast_count()
        print(f"  (estimation avant via rowid : {before:,})", flush=True)
    else:
        try:
            before = raw_count()
        except Exception:
            before = 0

    if next_num > max(nums) if nums else 7:
        out = _write_marker_batch(next_num, prefix)
    else:
        out = SCRIPTS / f"aliases_batch{next_num}.py"

    t0 = time.perf_counter()
    added = apply_prefix_and_record(prefix, batch_num=next_num)
    elapsed = time.perf_counter() - t0

    total = fast_count() if _db_is_large() else raw_count()

    from actions.alias_store import _write_stamp

    _write_stamp()
    _update_stub(total)

    print(f"Batch {next_num} — préfixe « {prefix} » ({elapsed:.1f}s)", flush=True)
    print(f"  avant     : {before:,}", flush=True)
    print(f"  ajoutés   : {added:,}", flush=True)
    print(f"  total     : {total:,}", flush=True)
    print(f"  écrit     : {out.name}", flush=True)
    return next_num, before, added, prefix


def main() -> None:
    parser = argparse.ArgumentParser(description="Double le catalogue de sites ARIA")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    for i in range(args.repeat):
        if i > 0:
            print()
        _require_db_under_limit()
        _require_disk_space()
        double_once()


if __name__ == "__main__":
    main()
