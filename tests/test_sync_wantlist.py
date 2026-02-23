"""Tests for wantlist sync operations."""

from unittest.mock import MagicMock, patch

import pytest

from discogs_sync.models import InputRecord, SyncActionType
from discogs_sync.sync_wantlist import sync_wantlist, add_to_wantlist, remove_from_wantlist


class TestSyncWantlist:
    @patch("discogs_sync.sync_wantlist._add_to_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_add_new_items(self, mock_search, mock_resolve, mock_get_ids, mock_add):
        """Items not in wantlist should be added."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Radiohead", album="OK Computer")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=123, master_id=3425,
            title="OK Computer", artist="Radiohead", matched=True, score=0.9,
        )
        mock_resolve.return_value = 123
        mock_get_ids.return_value = set()  # empty wantlist

        client = MagicMock()
        report = sync_wantlist(client, [record])

        assert report.added == 1
        assert report.errors == 0
        mock_add.assert_called_once()

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_skip_existing_items(self, mock_search, mock_resolve, mock_get_ids):
        """Items already in wantlist should be skipped."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Radiohead", album="OK Computer")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=123, master_id=3425,
            title="OK Computer", artist="Radiohead", matched=True, score=0.9,
        )
        mock_resolve.return_value = 123
        mock_get_ids.return_value = {123}  # already in wantlist

        client = MagicMock()
        report = sync_wantlist(client, [record])

        assert report.skipped == 1
        assert report.added == 0

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_unresolved_items(self, mock_search, mock_get_ids):
        """Items that can't be found should be errors."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Unknown", album="Unknown Album")
        mock_search.return_value = SearchResult(
            input_record=record, matched=False, error="No match found",
        )
        mock_get_ids.return_value = set()

        client = MagicMock()
        report = sync_wantlist(client, [record])

        assert report.errors == 1
        assert report.added == 0

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_dry_run_no_changes(self, mock_search, mock_resolve, mock_get_ids):
        """Dry run should not call add."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Radiohead", album="OK Computer")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=123, matched=True, score=0.9,
        )
        mock_resolve.return_value = 123
        mock_get_ids.return_value = set()

        client = MagicMock()
        report = sync_wantlist(client, [record], dry_run=True)

        assert report.added == 1  # reported as add
        # But the actual API add should not be called
        # (it's internal, but we can check the reason)
        assert report.actions[0].reason == "Dry run"

    @patch("discogs_sync.sync_wantlist._remove_from_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_remove_extras(self, mock_search, mock_resolve, mock_get_ids, mock_remove):
        """With --remove-extras, items not in input should be removed."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Radiohead", album="OK Computer")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=123, matched=True, score=0.9,
        )
        mock_resolve.return_value = 123
        mock_get_ids.return_value = {123, 456}  # 456 is extra

        client = MagicMock()
        report = sync_wantlist(client, [record], remove_extras=True)

        assert report.removed == 1
        mock_remove.assert_called_once()


class TestAddToWantlist:
    @patch("discogs_sync.sync_wantlist._add_to_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    def test_add_by_release_id(self, mock_get_ids, mock_add):
        """Adding by release_id directly."""
        mock_get_ids.return_value = set()
        client = MagicMock()

        action = add_to_wantlist(client, release_id=123)

        assert action.action == SyncActionType.ADD
        assert action.release_id == 123

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    def test_skip_duplicate(self, mock_get_ids):
        """Should skip if already in wantlist."""
        mock_get_ids.return_value = {123}
        client = MagicMock()

        action = add_to_wantlist(client, release_id=123)

        assert action.action == SyncActionType.SKIP
        assert "Already in wantlist" in action.reason


class TestRemoveFromWantlist:
    @patch("discogs_sync.sync_wantlist._remove_from_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    def test_remove_existing(self, mock_get_ids, mock_remove):
        """Removing an item that exists."""
        mock_get_ids.return_value = {123}
        client = MagicMock()

        action = remove_from_wantlist(client, release_id=123)

        assert action.action == SyncActionType.REMOVE
        mock_remove.assert_called_once()

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    def test_remove_nonexistent(self, mock_get_ids):
        """Removing an item not in wantlist should skip."""
        mock_get_ids.return_value = set()
        client = MagicMock()

        action = remove_from_wantlist(client, release_id=123)

        assert action.action == SyncActionType.SKIP
        assert "Not in wantlist" in action.reason
