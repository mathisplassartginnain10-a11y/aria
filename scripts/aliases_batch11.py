"""Batch 11 — doublement via préfixe vocal « lance »."""
from __future__ import annotations

import importlib
import re
from pathlib import Path


def _merged_before() -> dict[str, str]:
    import scripts.gen_aliases_extra as gen

    merged = dict(gen.EXTRA)
    scripts = Path(__file__).resolve().parent
    nums = sorted(
        int(m.group(1))
        for p in scripts.glob('aliases_batch*.py')
        if (m := re.fullmatch(r'aliases_batch(\d+)', p.stem))
    )
    for n in nums:
        if n >= 11:
            continue
        mod = importlib.import_module(f'scripts.aliases_batch{n}')
        fn = getattr(mod, f'get_batch{n}')
        for key, domain in fn().items():
            merged.setdefault(key, domain)
    return merged


def get_batch11() -> dict[str, str]:
    prior = _merged_before()
    existing: set[str] = set(prior.keys())
    prefix = "lance"
    d: dict[str, str] = {}
    for alias, domain in prior.items():
        key = f'{prefix} {alias}'.strip().lower()
        if key not in existing:
            d[key] = domain
            existing.add(key)
    return d
