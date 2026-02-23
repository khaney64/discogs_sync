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
        mock_get_ids.return_value = ({}, set(), [])  # empty collection

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
        mock_get_ids.return_value = ({456: [1001]}, {1000}, [("Miles Davis", "Kind of Blue", 456)])

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
        mock_get_ids.return_value = ({}, set(), [])

        client = MagicMock()
        report = sync_collection(client, [record], dry_run=True)

        assert report.added == 1
        assert report.actions[0].reason == "Dry run"


class TestAddToCollection:
    @patch("discogs_sync.sync_collection._add_to_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_add_by_release_id(self, mock_get_ids, mock_add):
        mock_get_ids.return_value = ({}, set(), [])
        client = MagicMock()

        action = add_to_collection(client, release_id=456)

        assert action.action == SyncActionType.ADD
        assert action.release_id == 456

    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_skip_duplicate_default(self, mock_get_ids):
        mock_get_ids.return_value = ({456: [1001]}, {1000}, [("Miles Davis", "Kind of Blue", 456)])
        client = MagicMock()

        action = add_to_collection(client, release_id=456)

        assert action.action == SyncActionType.SKIP
        assert "Already in collection" in action.reason

    @patch("discogs_sync.sync_collection._add_to_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_allow_duplicate(self, mock_get_ids, mock_add):
        mock_get_ids.return_value = ({456: [1001]}, {1000}, [("Miles Davis", "Kind of Blue", 456)])
        client = MagicMock()

        action = add_to_collection(client, release_id=456, allow_duplicate=True)

        assert action.action == SyncActionType.ADD
        mock_add.assert_called_once()


class TestRemoveFromCollection:
    @patch("discogs_sync.sync_collection._remove_from_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_remove_existing(self, mock_get_ids, mock_remove):
        mock_get_ids.return_value = ({456: [1001]}, {1000}, [("Miles Davis", "Kind of Blue", 456)])
        client = MagicMock()

        action = remove_from_collection(client, release_id=456)

        assert action.action == SyncActionType.REMOVE
        mock_remove.assert_called_once()

    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_remove_nonexistent(self, mock_get_ids):
        mock_get_ids.return_value = ({}, set(), [])
        client = MagicMock()

        action = remove_from_collection(client, release_id=456)

        assert action.action == SyncActionType.SKIP


class TestMasterIdMatching:
    """Tests for master_id-based duplicate detection in collection sync."""

    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.sync_collection.resolve_to_release_id")
    @patch("discogs_sync.sync_collection.search_release")
    def test_skip_when_different_pressing_in_collection(self, mock_search, mock_resolve, mock_get_ids):
        """Different release_id but same master_id should SKIP."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Miles Davis", album="Kind of Blue")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, master_id=1000,
            title="Kind of Blue", artist="Miles Davis", matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        # Collection has release_id=789 (different pressing) but same master_id=1000
        mock_get_ids.return_value = ({789: [1001]}, {1000}, [("Miles Davis", "Kind of Blue", 789)])

        client = MagicMock()
        report = sync_collection(client, [record])

        assert report.skipped == 1
        assert report.added == 0

    @patch("discogs_sync.sync_collection._add_to_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.sync_collection.resolve_to_release_id")
    @patch("discogs_sync.sync_collection.search_release")
    def test_add_when_no_master_id_match(self, mock_search, mock_resolve, mock_get_ids, mock_add):
        """Different release_id and different master_id should ADD."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Miles Davis", album="Kind of Blue")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, master_id=1000,
            title="Kind of Blue", artist="Miles Davis", matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        # Collection has a different master entirely
        mock_get_ids.return_value = ({789: [1001]}, {2000}, [("John Coltrane", "A Love Supreme", 789)])

        client = MagicMock()
        report = sync_collection(client, [record])

        assert report.added == 1
        assert report.skipped == 0
        mock_add.assert_called_once()

    @patch("discogs_sync.sync_collection._add_to_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.sync_collection.resolve_to_release_id")
    @patch("discogs_sync.sync_collection.search_release")
    def test_add_when_result_has_no_master_id(self, mock_search, mock_resolve, mock_get_ids, mock_add):
        """When search result has no master_id and no fuzzy match, should ADD."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Miles Davis", album="Kind of Blue")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, master_id=None,
            title="Kind of Blue", artist="Miles Davis", matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        # Collection has a different album entirely (no release_id, master_id, or fuzzy match)
        mock_get_ids.return_value = ({789: [1001]}, {1000}, [("John Coltrane", "A Love Supreme", 789)])

        client = MagicMock()
        report = sync_collection(client, [record])

        assert report.added == 1
        assert report.skipped == 0

    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_add_to_collection_skip_by_master_id(self, mock_get_ids):
        """add_to_collection should skip when master_id matches even if release_id differs."""
        # Collection has release 789 with master 1000
        mock_get_ids.return_value = ({789: [1001]}, {1000}, [("Miles Davis", "Kind of Blue", 789)])
        client = MagicMock()

        action = add_to_collection(client, release_id=456, master_id=1000)

        assert action.action == SyncActionType.SKIP
        assert "Already in collection" in action.reason


class TestFuzzyMatching:
    """Tests for fuzzy artist+title duplicate detection in collection sync."""

    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.sync_collection.resolve_to_release_id")
    @patch("discogs_sync.sync_collection.search_release")
    def test_skip_fuzzy_match_different_release_no_master(self, mock_search, mock_resolve, mock_get_ids):
        """Different release_id, no master_id, but matching artist+title should SKIP via fuzzy match."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="The Alan Parsons Project", album="I Robot")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, master_id=None,
            title="I Robot", artist="The Alan Parsons Project", matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        # Collection has different release_id, no master_id in set, but same artist+title
        mock_get_ids.return_value = ({789: [1001]}, set(), [("The Alan Parsons Project", "I Robot", 789)])

        client = MagicMock()
        report = sync_collection(client, [record])

        assert report.skipped == 1
        assert report.added == 0
        assert "fuzzy match" in report.actions[0].reason

    @patch("discogs_sync.sync_collection._add_to_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.sync_collection.resolve_to_release_id")
    @patch("discogs_sync.sync_collection.search_release")
    def test_add_when_no_fuzzy_match(self, mock_search, mock_resolve, mock_get_ids, mock_add):
        """Different release_id, no master_id, different artist+title should ADD."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Supertramp", album="Breakfast In America")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, master_id=None,
            title="Breakfast In America", artist="Supertramp", matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        # Collection has a completely different album
        mock_get_ids.return_value = ({789: [1001]}, set(), [("Pink Floyd", "Dark Side of the Moon", 789)])

        client = MagicMock()
        report = sync_collection(client, [record])

        assert report.added == 1
        assert report.skipped == 0
        mock_add.assert_called_once()

    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.sync_collection.resolve_to_release_id")
    @patch("discogs_sync.sync_collection.search_release")
    def test_skip_fuzzy_match_slight_title_variation(self, mock_search, mock_resolve, mock_get_ids):
        """Slight title case variation should still fuzzy match and SKIP."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Supertramp", album="Breakfast in America")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, master_id=None,
            title="Breakfast in America", artist="Supertramp", matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        # Collection has "Breakfast In America" (capital I)
        mock_get_ids.return_value = ({789: [1001]}, set(), [("Supertramp", "Breakfast In America", 789)])

        client = MagicMock()
        report = sync_collection(client, [record])

        assert report.skipped == 1
        assert report.added == 0
        assert "fuzzy match" in report.actions[0].reason

    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_add_to_collection_skip_by_fuzzy_match(self, mock_get_ids):
        """add_to_collection should skip via fuzzy match when release_id/master_id don't match."""
        mock_get_ids.return_value = ({789: [1001]}, set(), [("Quincy Jones", "The Dude", 789)])
        client = MagicMock()

        action = add_to_collection(client, release_id=456, artist="Quincy Jones", album="The Dude")

        assert action.action == SyncActionType.SKIP
        assert "fuzzy match" in action.reason
