"""Shared test fixtures."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def sample_csv(fixtures_dir):
    return fixtures_dir / "sample_wantlist.csv"


@pytest.fixture
def sample_json(fixtures_dir):
    return fixtures_dir / "sample_wantlist.json"


@pytest.fixture
def tmp_csv(tmp_path):
    """Factory for creating temporary CSV files."""

    def _make(content: str) -> Path:
        p = tmp_path / "test.csv"
        p.write_text(content, encoding="utf-8")
        return p

    return _make


@pytest.fixture
def tmp_json(tmp_path):
    """Factory for creating temporary JSON files."""

    def _make(content: str) -> Path:
        p = tmp_path / "test.json"
        p.write_text(content, encoding="utf-8")
        return p

    return _make
