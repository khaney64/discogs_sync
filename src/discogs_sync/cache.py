"""File-based TTL cache for list results (wantlist, collection, marketplace)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

CACHE_TTL_SECONDS = 3600  # 1 hour


def get_cache_dir() -> Path:
    """Return the directory where cache files are stored (~/.discogs-sync)."""
    return Path.home() / ".discogs-sync"


def _cache_path(name: str) -> Path:
    return get_cache_dir() / f"{name}_cache.json"


def read_cache(name: str) -> list[dict] | None:
    """Return cached items if present and within TTL, else None.

    Args:
        name: Cache name, e.g. ``"wantlist"`` or ``"collection"``.

    Returns:
        List of raw item dicts, or ``None`` on cache miss / expiry / error.
    """
    path = _cache_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(data["cached_at"])
        now = datetime.now(timezone.utc)
        age = (now - cached_at).total_seconds()
        if age > CACHE_TTL_SECONDS:
            return None
        return data["items"]
    except (KeyError, ValueError, json.JSONDecodeError, OSError):
        return None


def write_cache(name: str, items: list[dict]) -> None:
    """Write items to the cache file with the current UTC timestamp.

    Args:
        name: Cache name, e.g. ``"wantlist"`` or ``"collection"``.
        items: List of raw item dicts (from ``to_dict()``).

    Failures are silently swallowed — a cache write error is non-fatal.
    """
    path = _cache_path(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass  # non-fatal


def invalidate_cache(name: str) -> None:
    """Delete the cache file for *name*. Silent no-op if file does not exist.

    Args:
        name: Cache name, e.g. ``"wantlist"`` or ``"collection"``.
    """
    path = _cache_path(name)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def marketplace_cache_name(
    cache_type: str,
    *key_parts: object,
) -> str:
    """Return a stable cache name for a marketplace search.

    The name is ``marketplace_{cache_type}_{md5}`` where the MD5 is computed
    over the pipe-joined string representation of *key_parts*. This keeps
    filenames safe regardless of artist/album content.

    Args:
        cache_type: One of ``"release"``, ``"master"``, or ``"artist"``.
        *key_parts: Values that together uniquely identify the search
            (IDs, filters, flags, etc.).

    Returns:
        A string suitable for use as the *name* argument to
        :func:`read_cache`, :func:`write_cache`, and
        :func:`invalidate_cache`.
    """
    raw = "|".join(str(p) for p in key_parts)
    digest = hashlib.md5(raw.encode()).hexdigest()[:16]
    return f"marketplace_{cache_type}_{digest}"
