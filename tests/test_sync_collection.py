"""Tests for collection sync operations."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from discogs_sync.cli import main
from discogs_sync.models import CollectionItem, InputRecord, SyncActionType
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


class TestCollectionListSearch:
    """Tests for collection list --search filtering."""

    ITEMS = [
        CollectionItem(instance_id=1, release_id=10, artist="Miles Davis", title="Kind of Blue"),
        CollectionItem(instance_id=2, release_id=20, artist="John Coltrane", title="A Love Supreme"),
        CollectionItem(instance_id=3, release_id=30, artist="Miles Davis", title="Bitches Brew"),
    ]

    @pytest.fixture(autouse=True)
    def patch_cache(self):
        """Prevent real cache reads/writes during list command tests."""
        with patch("discogs_sync.cache.read_cache", return_value=None), \
             patch("discogs_sync.cache.write_cache"):
            yield

    @patch("discogs_sync.sync_collection.list_collection", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_search_matches_artist(self, _mock_client, _mock_list):
        """--search should filter by artist name."""
        runner = CliRunner()
        result = runner.invoke(main, ["collection", "list", "--search", "miles", "--output-format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 2
        artists = {i["artist"] for i in data["items"]}
        assert artists == {"Miles Davis"}

    @patch("discogs_sync.sync_collection.list_collection", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_search_matches_title(self, _mock_client, _mock_list):
        """--search should filter by title."""
        runner = CliRunner()
        result = runner.invoke(main, ["collection", "list", "--search", "love supreme", "--output-format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 1
        assert data["items"][0]["title"] == "A Love Supreme"

    @patch("discogs_sync.sync_collection.list_collection", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_search_no_matches(self, _mock_client, _mock_list):
        """--search with no matches returns empty list."""
        runner = CliRunner()
        result = runner.invoke(main, ["collection", "list", "--search", "beatles", "--output-format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 0
        assert data["items"] == []

    @patch("discogs_sync.sync_collection.list_collection", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_no_search_returns_all(self, _mock_client, _mock_list):
        """Without --search, all items are returned."""
        runner = CliRunner()
        result = runner.invoke(main, ["collection", "list", "--output-format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 3

    @patch("discogs_sync.sync_collection.list_collection", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_cache_hit_skips_api(self, _mock_client, mock_list):
        """When cache has a valid hit, list_collection should not be called."""
        cached_dicts = [i.to_dict() for i in self.ITEMS]
        with patch("discogs_sync.cache.read_cache", return_value=cached_dicts), \
             patch("discogs_sync.cache.write_cache") as mock_write:
            runner = CliRunner()
            result = runner.invoke(main, ["collection", "list", "--output-format", "json"])
        assert result.exit_code == 0
        mock_list.assert_not_called()
        mock_write.assert_not_called()
        data = json.loads(result.output)
        assert data["total"] == 3

    @patch("discogs_sync.sync_collection.list_collection", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_no_cache_flag_bypasses_read_but_writes(self, _mock_client, mock_list):
        """--no-cache forces API call and still updates the cache."""
        with patch("discogs_sync.cache.read_cache") as mock_read, \
             patch("discogs_sync.cache.write_cache") as mock_write:
            runner = CliRunner()
            result = runner.invoke(main, ["collection", "list", "--no-cache", "--output-format", "json"])
        assert result.exit_code == 0
        mock_read.assert_not_called()
        mock_list.assert_called_once()
        mock_write.assert_called_once()

    @patch("discogs_sync.sync_collection.list_collection", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_non_zero_folder_id_skips_cache(self, _mock_client, mock_list):
        """Non-default folder-id should bypass cache entirely (no read or write)."""
        with patch("discogs_sync.cache.read_cache") as mock_read, \
             patch("discogs_sync.cache.write_cache") as mock_write:
            runner = CliRunner()
            result = runner.invoke(main, ["collection", "list", "--folder-id", "1", "--output-format", "json"])
        assert result.exit_code == 0
        mock_read.assert_not_called()
        mock_write.assert_not_called()


class TestCollectionCacheInvalidation:
    """Tests that mutating collection commands invalidate the cache."""

    @patch("discogs_sync.cache.invalidate_cache")
    @patch("discogs_sync.sync_collection.add_to_collection")
    @patch("discogs_sync.client_factory.build_client")
    def test_add_invalidates_cache(self, _mock_client, mock_add, mock_invalidate):
        """collection add should call invalidate_cache('collection')."""
        from discogs_sync.models import SyncAction, SyncActionType
        mock_add.return_value = SyncAction(
            action=SyncActionType.ADD, release_id=456, artist="Miles Davis", title="Kind of Blue",
        )
        runner = CliRunner()
        result = runner.invoke(main, ["collection", "add", "--release-id", "456"])
        assert result.exit_code == 0
        mock_invalidate.assert_called_once_with("collection")

    @patch("discogs_sync.cache.invalidate_cache")
    @patch("discogs_sync.sync_collection.remove_from_collection")
    @patch("discogs_sync.client_factory.build_client")
    def test_remove_invalidates_cache(self, _mock_client, mock_remove, mock_invalidate):
        """collection remove should call invalidate_cache('collection')."""
        from discogs_sync.models import SyncAction, SyncActionType
        mock_remove.return_value = SyncAction(
            action=SyncActionType.REMOVE, release_id=456, artist="Miles Davis", title="Kind of Blue",
        )
        runner = CliRunner()
        result = runner.invoke(main, ["collection", "remove", "--release-id", "456"])
        assert result.exit_code == 0
        mock_invalidate.assert_called_once_with("collection")
