"""Tests for collection sync operations."""

from unittest.mock import MagicMock, patch

import pytest

from discogs_sync.models import InputRecord, SyncActionType
from discogs_sync.sync_collection import sync_collection, add_to_collection, remove_from_collection


class TestSyncCollection:
    @patch("discogs_sync.sync_collection._add_to_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.sync_collection.resolve_to_release_id")
    @patch("discogs_sync.sync_collection.search_release")
    def test_add_new_items(self, mock_search, mock_resolve, mock_get_ids, mock_add):
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Miles Davis", album="Kind of Blue")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, master_id=1000,
            title="Kind of Blue", artist="Miles Davis", matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        mock_get_ids.return_value = {}  # empty collection

        client = MagicMock()
        report = sync_collection(client, [record])

        assert report.added == 1
        assert report.errors == 0
        mock_add.assert_called_once()

    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.sync_collection.resolve_to_release_id")
    @patch("discogs_sync.sync_collection.search_release")
    def test_skip_existing(self, mock_search, mock_resolve, mock_get_ids):
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Miles Davis", album="Kind of Blue")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        mock_get_ids.return_value = {456: [1001]}

        client = MagicMock()
        report = sync_collection(client, [record])

        assert report.skipped == 1
        assert report.added == 0

    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.sync_collection.resolve_to_release_id")
    @patch("discogs_sync.sync_collection.search_release")
    def test_dry_run(self, mock_search, mock_resolve, mock_get_ids):
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Miles Davis", album="Kind of Blue")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        mock_get_ids.return_value = {}

        client = MagicMock()
        report = sync_collection(client, [record], dry_run=True)

        assert report.added == 1
        assert report.actions[0].reason == "Dry run"


class TestAddToCollection:
    @patch("discogs_sync.sync_collection._add_to_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_add_by_release_id(self, mock_get_ids, mock_add):
        mock_get_ids.return_value = {}
        client = MagicMock()

        action = add_to_collection(client, release_id=456)

        assert action.action == SyncActionType.ADD
        assert action.release_id == 456

    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_skip_duplicate_default(self, mock_get_ids):
        mock_get_ids.return_value = {456: [1001]}
        client = MagicMock()

        action = add_to_collection(client, release_id=456)

        assert action.action == SyncActionType.SKIP
        assert "Already in collection" in action.reason

    @patch("discogs_sync.sync_collection._add_to_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_allow_duplicate(self, mock_get_ids, mock_add):
        mock_get_ids.return_value = {456: [1001]}
        client = MagicMock()

        action = add_to_collection(client, release_id=456, allow_duplicate=True)

        assert action.action == SyncActionType.ADD
        mock_add.assert_called_once()


class TestRemoveFromCollection:
    @patch("discogs_sync.sync_collection._remove_from_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_remove_existing(self, mock_get_ids, mock_remove):
        mock_get_ids.return_value = {456: [1001]}
        client = MagicMock()

        action = remove_from_collection(client, release_id=456)

        assert action.action == SyncActionType.REMOVE
        mock_remove.assert_called_once()

    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_remove_nonexistent(self, mock_get_ids):
        mock_get_ids.return_value = {}
        client = MagicMock()

        action = remove_from_collection(client, release_id=456)

        assert action.action == SyncActionType.SKIP
