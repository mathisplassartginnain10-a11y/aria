"""
Double le catalogue de sites connus.

Chaque exécution = un nouveau batch (variantes vocales sur tout le catalogue).
Préfixes alternés : open → ouvrir → go to → va sur → lance → visite → site → …

Usage:
    python scripts/double_sites.py
    python scripts/double_sites.py --repeat 5
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent


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


def double_once() -> tuple[int, int, int, str]:
    sys.path.insert(0, str(ROOT))
    from actions.alias_store import apply_prefix_and_record, prefix_for_batch, raw_count

    nums = _batch_numbers()
    next_num = (max(nums) + 1) if nums else 7
    prefix = prefix_for_batch(next_num)
    before = raw_count()

    out = _write_marker_batch(next_num, prefix)

    t0 = time.perf_counter()
    added = apply_prefix_and_record(prefix)
    total = raw_count()
    elapsed = time.perf_counter() - t0

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
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Nombre de doublements consécutifs (défaut: 1)",
    )
    args = parser.parse_args()

    for i in range(args.repeat):
        if i > 0:
            print()
        double_once()


if __name__ == "__main__":
    main()
