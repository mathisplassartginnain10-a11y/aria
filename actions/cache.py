"""Cache générique TTL par catégorie (spec v15)."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

_DEFAULT_TTLS: dict[str, int] = {
    "meteo": 600,
    "news": 900,
    "aviation": 300,
    "search": 300,
    "default": 600,
}
_MAX_ENTRIES = 500
_store: OrderedDict[str, tuple[float, Any]] = OrderedDict()


def _ttl(category: str) -> int:
    return _DEFAULT_TTLS.get(category, _DEFAULT_TTLS["default"])


def get(category: str, key: str) -> Any | None:
    cache_key = f"{category}:{key}"
    entry = _store.get(cache_key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > _ttl(category):
        _store.pop(cache_key, None)
        return None
    _store.move_to_end(cache_key)
    return value


def set(category: str, key: str, value: Any) -> None:
    cache_key = f"{category}:{key}"
    _store[cache_key] = (time.time(), value)
    _store.move_to_end(cache_key)
    while len(_store) > _MAX_ENTRIES:
        _store.popitem(last=False)
