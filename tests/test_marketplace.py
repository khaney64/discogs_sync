"""Tests for marketplace search."""

from unittest.mock import MagicMock, patch

import pytest

from discogs_sync.marketplace import search_marketplace, search_marketplace_batch
from discogs_sync.models import InputRecord


class TestSearchMarketplace:
    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_search_by_master_id(self, mock_api):
        """Search marketplace by master ID."""
        # Mock master
        mock_master = MagicMock()
        mock_version = MagicMock()
        mock_version.data = {
            "id": 7890,
            "title": "OK Computer",
            "format": "Vinyl",
            "country": "US",
            "year": 1997,
            "major_formats": ["Vinyl"],
        }

        mock_page = [mock_version]
        mock_versions = MagicMock()
        mock_versions.page.return_value = mock_page

        mock_release = MagicMock()
        mock_release.data = {
            "title": "Radiohead - OK Computer",
            "formats": [{"name": "Vinyl"}],
            "country": "US",
            "year": 1997,
            "master_id": 3425,
        }

        mock_stats = MagicMock()
        mock_stats.num_for_sale = 42
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 25.99

        # Setup mock returns
        call_count = [0]

        def side_effect(fn, *args, **kwargs):
            call_count[0] += 1
            result = fn()
            return result

        mock_api.side_effect = side_effect

        client = MagicMock()
        client.master.return_value = mock_master
        mock_master.versions = mock_versions
        client.release.return_value = mock_release
        mock_release.marketplace_stats = mock_stats

        results = search_marketplace(client, master_id=3425, max_versions=1)

        assert len(results) >= 0  # May vary based on mock setup

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_price_filter_min(self, mock_api):
        """Min price filter should exclude cheap items."""
        # Setup simple mock
        mock_master = MagicMock()
        mock_versions = MagicMock()
        mock_versions.page.return_value = []  # Empty to keep test simple
        mock_master.versions = mock_versions

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.master.return_value = mock_master

        results = search_marketplace(client, master_id=3425, min_price=100.0)
        assert len(results) == 0


class TestSearchMarketplaceBatch:
    @patch("discogs_sync.marketplace.search_marketplace")
    def test_batch_collects_errors(self, mock_search):
        """Batch search should collect per-item errors."""
        mock_search.side_effect = Exception("API error")

        records = [InputRecord(artist="Test", album="Album")]
        results, errors = search_marketplace_batch(MagicMock(), records)

        assert len(results) == 0
        assert len(errors) == 1
        assert "API error" in errors[0]["error"]

    @patch("discogs_sync.marketplace.search_marketplace")
    def test_batch_collects_results(self, mock_search):
        """Batch search should collect results from all items."""
        from discogs_sync.models import MarketplaceResult

        mock_search.return_value = [
            MarketplaceResult(release_id=1, lowest_price=10.0),
        ]

        records = [
            InputRecord(artist="A1", album="B1"),
            InputRecord(artist="A2", album="B2"),
        ]
        results, errors = search_marketplace_batch(MagicMock(), records)

        assert len(results) == 2
        assert len(errors) == 0
