"""Tests for the file-based cache module."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from discogs_sync.cache import read_cache, write_cache, invalidate_cache, CACHE_TTL_SECONDS
from discogs_sync.models import WantlistItem, CollectionItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_raw_cache(cache_dir: Path, name: str, items: list[dict], age_seconds: float = 0) -> Path:
    """Write a cache file with a controlled timestamp."""
    cached_at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    data = {"cached_at": cached_at.isoformat(), "items": items}
    path = cache_dir / f"{name}_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


SAMPLE_WANTLIST_DICTS = [
    {"release_id": 1, "master_id": 10, "title": "OK Computer", "artist": "Radiohead",
     "format": "Vinyl", "year": 1997, "notes": None},
]

SAMPLE_COLLECTION_DICTS = [
    {"instance_id": 100, "release_id": 1, "master_id": 10, "folder_id": 0,
     "title": "Kind of Blue", "artist": "Miles Davis", "format": "CD", "year": 1959},
]


# ---------------------------------------------------------------------------
# read_cache tests
# ---------------------------------------------------------------------------

class TestReadCache:
    def test_returns_none_when_file_absent(self, tmp_path):
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            assert read_cache("wantlist") is None

    def test_returns_items_within_ttl(self, tmp_path):
        _write_raw_cache(tmp_path, "wantlist", SAMPLE_WANTLIST_DICTS, age_seconds=60)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            result = read_cache("wantlist")
        assert result == SAMPLE_WANTLIST_DICTS

    def test_returns_none_when_expired(self, tmp_path):
        _write_raw_cache(tmp_path, "wantlist", SAMPLE_WANTLIST_DICTS, age_seconds=CACHE_TTL_SECONDS + 1)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            assert read_cache("wantlist") is None

    def test_returns_items_on_exactly_ttl_boundary(self, tmp_path):
        """Exactly at TTL is still valid (expiry uses strictly-greater-than)."""
        _write_raw_cache(tmp_path, "wantlist", SAMPLE_WANTLIST_DICTS, age_seconds=CACHE_TTL_SECONDS)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            assert read_cache("wantlist") == SAMPLE_WANTLIST_DICTS

    def test_returns_none_on_corrupt_json(self, tmp_path):
        path = tmp_path / "wantlist_cache.json"
        path.write_text("not json", encoding="utf-8")
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            assert read_cache("wantlist") is None

    def test_returns_none_on_missing_keys(self, tmp_path):
        path = tmp_path / "wantlist_cache.json"
        path.write_text(json.dumps({"items": []}), encoding="utf-8")
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            assert read_cache("wantlist") is None

    def test_cache_names_are_independent(self, tmp_path):
        _write_raw_cache(tmp_path, "wantlist", SAMPLE_WANTLIST_DICTS, age_seconds=30)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            assert read_cache("collection") is None
            assert read_cache("wantlist") == SAMPLE_WANTLIST_DICTS


# ---------------------------------------------------------------------------
# write_cache tests
# ---------------------------------------------------------------------------

class TestWriteCache:
    def test_creates_file(self, tmp_path):
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            write_cache("wantlist", SAMPLE_WANTLIST_DICTS)
        assert (tmp_path / "wantlist_cache.json").exists()

    def test_written_file_is_valid_json(self, tmp_path):
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            write_cache("wantlist", SAMPLE_WANTLIST_DICTS)
        raw = json.loads((tmp_path / "wantlist_cache.json").read_text(encoding="utf-8"))
        assert "cached_at" in raw
        assert raw["items"] == SAMPLE_WANTLIST_DICTS

    def test_cached_at_is_recent(self, tmp_path):
        before = datetime.now(timezone.utc)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            write_cache("wantlist", SAMPLE_WANTLIST_DICTS)
        after = datetime.now(timezone.utc)
        raw = json.loads((tmp_path / "wantlist_cache.json").read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(raw["cached_at"])
        assert before <= ts <= after

    def test_round_trip_through_read(self, tmp_path):
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            write_cache("collection", SAMPLE_COLLECTION_DICTS)
            result = read_cache("collection")
        assert result == SAMPLE_COLLECTION_DICTS

    def test_creates_directory_if_missing(self, tmp_path):
        nested = tmp_path / "nested" / "dir"
        with patch("discogs_sync.cache.get_cache_dir", return_value=nested):
            write_cache("wantlist", [])
        assert (nested / "wantlist_cache.json").exists()

    def test_write_failure_is_silent(self, tmp_path):
        """write_cache should not raise even if the directory cannot be created."""
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            # Point at a file so mkdir will fail
            bad_file = tmp_path / "wantlist_cache.json"
            bad_file.write_text("placeholder", encoding="utf-8")
            bad_file.chmod(0o444)
            # Should complete without raising
            try:
                write_cache("wantlist", SAMPLE_WANTLIST_DICTS)
            finally:
                bad_file.chmod(0o644)


# ---------------------------------------------------------------------------
# invalidate_cache tests
# ---------------------------------------------------------------------------

class TestInvalidateCache:
    def test_deletes_existing_file(self, tmp_path):
        _write_raw_cache(tmp_path, "wantlist", SAMPLE_WANTLIST_DICTS)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            invalidate_cache("wantlist")
        assert not (tmp_path / "wantlist_cache.json").exists()

    def test_silent_when_file_absent(self, tmp_path):
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            invalidate_cache("wantlist")  # should not raise

    def test_only_deletes_named_cache(self, tmp_path):
        _write_raw_cache(tmp_path, "wantlist", SAMPLE_WANTLIST_DICTS)
        _write_raw_cache(tmp_path, "collection", SAMPLE_COLLECTION_DICTS)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            invalidate_cache("wantlist")
        assert not (tmp_path / "wantlist_cache.json").exists()
        assert (tmp_path / "collection_cache.json").exists()


# ---------------------------------------------------------------------------
# Model round-trip tests (from_dict / to_dict)
# ---------------------------------------------------------------------------

class TestModelRoundTrip:
    def test_wantlist_item_round_trip(self):
        original = WantlistItem(
            release_id=42, master_id=100, title="OK Computer",
            artist="Radiohead", format="Vinyl", year=1997, notes="repress",
        )
        assert WantlistItem.from_dict(original.to_dict()) == original

    def test_wantlist_item_round_trip_nulls(self):
        original = WantlistItem(release_id=42)
        assert WantlistItem.from_dict(original.to_dict()) == original

    def test_collection_item_round_trip(self):
        original = CollectionItem(
            instance_id=1, release_id=42, master_id=100, folder_id=0,
            title="Kind of Blue", artist="Miles Davis", format="CD", year=1959,
        )
        assert CollectionItem.from_dict(original.to_dict()) == original

    def test_collection_item_round_trip_nulls(self):
        original = CollectionItem(instance_id=1, release_id=42)
        assert CollectionItem.from_dict(original.to_dict()) == original
