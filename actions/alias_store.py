"""Chargement lazy des alias sites via SQLite (millions d'entrées)."""
from __future__ import annotations

import importlib
import re
import sqlite3
import time
from pathlib import Path

import app_paths

DB_PATH = app_paths.data_dir() / "site_aliases.db"
STAMP_PATH = app_paths.data_dir() / "site_aliases.stamp"
PREFIXES_PATH = app_paths.data_dir() / "site_aliases_prefixes.txt"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

VOICE_PREFIXES = ["open", "ouvrir", "go to", "va sur", "lance", "visite", "site"]


def _batch_numbers() -> list[int]:
    return sorted(
        int(m.group(1))
        for p in SCRIPTS_DIR.glob("aliases_batch*.py")
        if (m := re.fullmatch(r"aliases_batch(\d+)", p.stem))
    )


def prefix_for_batch(batch_num: int) -> str:
    idx = max(0, batch_num - 7)
    return VOICE_PREFIXES[idx % len(VOICE_PREFIXES)]


def expected_prefixes() -> list[str]:
    return [prefix_for_batch(n) for n in _batch_numbers() if n >= 8]


def _read_prefixes() -> list[str]:
    if not PREFIXES_PATH.exists():
        return []
    return [
        line.strip()
        for line in PREFIXES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_prefixes(prefixes: list[str]) -> None:
    PREFIXES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFIXES_PATH.write_text("\n".join(prefixes) + "\n", encoding="utf-8")


def _compute_stamp() -> str:
    parts: list[str] = []
    gen_path = SCRIPTS_DIR / "gen_aliases_extra.py"
    if gen_path.exists():
        parts.append(f"gen:{gen_path.stat().st_mtime_ns}")
    for n in _batch_numbers():
        p = SCRIPTS_DIR / f"aliases_batch{n}.py"
        parts.append(f"{n}:{p.stat().st_mtime_ns}:{p.stat().st_size}")
    if PREFIXES_PATH.exists():
        parts.append(f"prefixes:{PREFIXES_PATH.stat().st_mtime_ns}")
    return "|".join(parts)


def _stamp_matches() -> bool:
    if not DB_PATH.exists() or not STAMP_PATH.exists():
        return False
    try:
        return STAMP_PATH.read_text(encoding="utf-8") == _compute_stamp()
    except OSError:
        return False


def _write_stamp() -> None:
    STAMP_PATH.write_text(_compute_stamp(), encoding="utf-8")


def _checkpoint_wal() -> None:
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(DB_PATH, timeout=120)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def _merge_base() -> dict[str, str]:
    import scripts.gen_aliases_extra as gen

    merged = dict(gen.EXTRA)
    for n in _batch_numbers():
        if n >= 8:
            continue
        mod = importlib.import_module(f"scripts.aliases_batch{n}")
        fn = getattr(mod, f"get_batch{n}")
        batch = fn()
        if batch:
            for key, domain in batch.items():
                merged.setdefault(key, domain)
    return merged


def apply_prefix(prefix: str, *, _skip_ensure: bool = False) -> int:
    """Double le catalogue en SQL — ajoute « prefix alias » pour chaque entrée."""
    if not _skip_ensure:
        ensure_db()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=300)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-200000")
        needle = f"{prefix.strip().lower()} "
        before = conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]
        conn.execute(
            """
            INSERT OR IGNORE INTO aliases(key, domain)
            SELECT ? || key, domain FROM aliases
            WHERE key NOT LIKE ? || '%'
            """,
            (needle, prefix.strip().lower()),
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]
    finally:
        conn.close()
    _checkpoint_wal()
    return int(after - before)


def _remove_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            sidecar.unlink(missing_ok=True)


def rebuild_db() -> int:
    merged = _merge_base()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".tmp")

    for path in (tmp, DB_PATH.with_suffix(".old")):
        if path.exists():
            path.unlink(missing_ok=True)

    conn = sqlite3.connect(tmp)
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            "CREATE TABLE aliases (key TEXT PRIMARY KEY NOT NULL, domain TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO aliases(key, domain) VALUES (?, ?)",
            merged.items(),
        )
        conn.commit()
    finally:
        conn.close()

    _remove_sidecars(DB_PATH)
    if DB_PATH.exists():
        try:
            DB_PATH.unlink()
        except PermissionError:
            DB_PATH.replace(DB_PATH.with_suffix(".old"))
            _remove_sidecars(DB_PATH.with_suffix(".old"))

    tmp.replace(DB_PATH)
    _remove_sidecars(tmp)

    prefixes: list[str] = []
    for prefix in expected_prefixes():
        apply_prefix(prefix, _skip_ensure=True)
        prefixes.append(prefix)

    _write_prefixes(prefixes)
    _write_stamp()
    _checkpoint_wal()
    return raw_count()


def sync_missing_prefixes() -> int:
    """Applique les préfixes manquants depuis les fichiers batch 8+."""
    if not DB_PATH.exists():
        return rebuild_db()

    applied = _read_prefixes()
    expected = expected_prefixes()
    added_total = 0

    for prefix in expected[len(applied) :]:
        added_total += apply_prefix(prefix, _skip_ensure=True)
        applied.append(prefix)

    if applied != _read_prefixes():
        _write_prefixes(applied)
    _write_stamp()
    return added_total


def ensure_db() -> None:
    if not DB_PATH.exists():
        rebuild_db()
        return

    if _stamp_matches():
        return

    expected = expected_prefixes()
    applied = _read_prefixes()

    if len(expected) > len(applied):
        sync_missing_prefixes()
        return

    if expected == applied[: len(expected)]:
        _write_stamp()
        return

    t0 = time.perf_counter()
    count_val = rebuild_db()
    elapsed = time.perf_counter() - t0
    import logging

    logging.getLogger(__name__).info(
        "Index alias sites reconstruit — %s entrées en %.1fs", f"{count_val:,}", elapsed
    )


def raw_count() -> int:
    if not DB_PATH.exists():
        return 0
    conn = sqlite3.connect(DB_PATH, timeout=120)
    try:
        row = conn.execute("SELECT COUNT(*) FROM aliases").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def lookup(key: str) -> str | None:
    ensure_db()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        row = conn.execute(
            "SELECT domain FROM aliases WHERE key = ? LIMIT 1", (key.strip().lower(),)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def count() -> int:
    ensure_db()
    return raw_count()


def apply_prefix_and_record(prefix: str) -> int:
    added = apply_prefix(prefix, _skip_ensure=True)
    prefixes = _read_prefixes()
    prefixes.append(prefix)
    _write_prefixes(prefixes)
    _write_stamp()
    return added
