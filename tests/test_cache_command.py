"""Tests for the `cache clean` and `cache purge` CLI commands."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from discogs_sync.cache import CACHE_TTL_SECONDS
from discogs_sync.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_raw_cache(cache_dir: Path, name: str, age_seconds: float = 0) -> Path:
    cached_at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    data = {"cached_at": cached_at.isoformat(), "items": []}
    path = cache_dir / f"{name}_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# cache clean
# ---------------------------------------------------------------------------

class TestCacheClean:
    def test_removes_expired_files_and_reports_count(self, tmp_path):
        _write_raw_cache(tmp_path, "wantlist", age_seconds=CACHE_TTL_SECONDS + 10)
        _write_raw_cache(tmp_path, "collection", age_seconds=CACHE_TTL_SECONDS + 10)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            result = CliRunner().invoke(main, ["cache", "clean"])
        assert result.exit_code == 0
        assert "Removed 2 expired cache file(s)" in result.output

    def test_keeps_valid_files(self, tmp_path):
        _write_raw_cache(tmp_path, "wantlist", age_seconds=60)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            result = CliRunner().invoke(main, ["cache", "clean"])
        assert result.exit_code == 0
        assert "No expired cache files found" in result.output
        assert (tmp_path / "wantlist_cache.json").exists()

    def test_no_files_found_message(self, tmp_path):
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            result = CliRunner().invoke(main, ["cache", "clean"])
        assert result.exit_code == 0
        assert "No expired cache files found" in result.output

    def test_removes_expired_keeps_valid(self, tmp_path):
        _write_raw_cache(tmp_path, "wantlist", age_seconds=CACHE_TTL_SECONDS + 10)
        _write_raw_cache(tmp_path, "collection", age_seconds=60)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            result = CliRunner().invoke(main, ["cache", "clean"])
        assert result.exit_code == 0
        assert "Removed 1 expired cache file(s)" in result.output
        assert not (tmp_path / "wantlist_cache.json").exists()
        assert (tmp_path / "collection_cache.json").exists()


# ---------------------------------------------------------------------------
# cache purge
# ---------------------------------------------------------------------------

class TestCachePurge:
    def test_removes_all_files_and_reports_count(self, tmp_path):
        _write_raw_cache(tmp_path, "wantlist", age_seconds=60)
        _write_raw_cache(tmp_path, "collection", age_seconds=CACHE_TTL_SECONDS + 10)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            result = CliRunner().invoke(main, ["cache", "purge"])
        assert result.exit_code == 0
        assert "Removed 2 cache file(s)" in result.output
        assert not (tmp_path / "wantlist_cache.json").exists()
        assert not (tmp_path / "collection_cache.json").exists()

    def test_no_files_found_message(self, tmp_path):
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            result = CliRunner().invoke(main, ["cache", "purge"])
        assert result.exit_code == 0
        assert "No cache files found" in result.output

    def test_removes_valid_and_expired_files(self, tmp_path):
        for name in ["wantlist", "collection", "marketplace_release_abc123"]:
            _write_raw_cache(tmp_path, name, age_seconds=30)
        with patch("discogs_sync.cache.get_cache_dir", return_value=tmp_path):
            result = CliRunner().invoke(main, ["cache", "purge"])
        assert result.exit_code == 0
        assert "Removed 3 cache file(s)" in result.output
