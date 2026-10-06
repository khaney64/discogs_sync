"""Tests for collection sync operations."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from discogs_sync.cli import main
from discogs_sync.models import CollectionItem, InputRecord, SyncActionType
from discogs_sync.sync_collection import (
    _add_instance,
    _copy_instance_metadata,
    _find_instance,
    add_to_collection,
    remove_from_collection,
    replace_in_collection,
    sync_collection,
)


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

    @patch("discogs_sync.sync_collection._remove_from_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.sync_collection.resolve_to_release_id")
    @patch("discogs_sync.sync_collection.search_release")
    def test_unconfirmed_remove_extras_counts_instances(self, mock_search, mock_resolve, mock_get_ids, mock_remove):
        from discogs_sync.exceptions import SyncError
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Miles Davis", album="Kind of Blue")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        mock_get_ids.return_value = ({456: [1], 789: [2, 3]}, set(), [])

        with pytest.raises(SyncError, match="would delete 2 item"):
            sync_collection(MagicMock(), [record], remove_extras=True)

        mock_remove.assert_not_called()

    @patch("discogs_sync.sync_collection._remove_from_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.sync_collection.resolve_to_release_id")
    @patch("discogs_sync.sync_collection.search_release")
    def test_confirmed_remove_extras_removes_every_instance(self, mock_search, mock_resolve, mock_get_ids, mock_remove):
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Miles Davis", album="Kind of Blue")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        mock_get_ids.return_value = ({456: [1], 789: [2, 3]}, set(), [])

        report = sync_collection(MagicMock(), [record], remove_extras=True, confirm_removals=True)

        assert report.removed == 2
        assert mock_remove.call_count == 2


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

        action = remove_from_collection(client, release_id=456, confirm=True)

        assert action.action == SyncActionType.REMOVE
        mock_remove.assert_called_once()

    @patch("discogs_sync.sync_collection._remove_from_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    def test_unconfirmed_remove_previews_instance_without_removing(self, mock_get_ids, mock_remove):
        from discogs_sync.exceptions import ConfirmationRequiredError

        mock_get_ids.return_value = ({456: [1001, 1002]}, {1000}, [("Miles Davis", "Kind of Blue", 456)])

        with pytest.raises(ConfirmationRequiredError) as exc:
            remove_from_collection(MagicMock(), release_id=456)

        preview = exc.value.preview
        assert preview["instance_id"] == 1001
        assert preview["copies_owned"] == 2
        assert preview["artist"] == "Miles Davis"
        mock_remove.assert_not_called()

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
        mock_get_ids.return_value = ({789: [1001]}, {1000: {789}}, [("Miles Davis", "Kind of Blue", 789)])

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
        result = runner.invoke(main, ["collection", "remove", "--release-id", "456", "--yes"])
        assert result.exit_code == 0
        assert mock_remove.call_args.kwargs["confirm"] is True
        mock_invalidate.assert_called_once_with("collection")

    @patch("discogs_sync.cache.invalidate_cache")
    @patch("discogs_sync.sync_collection._remove_from_collection")
    @patch("discogs_sync.sync_collection._get_collection_release_ids")
    @patch("discogs_sync.client_factory.build_client")
    def test_remove_without_yes_exits_2(self, _mock_client, mock_get_ids, mock_remove, mock_invalidate):
        """collection remove without --yes refuses and changes nothing."""
        mock_get_ids.return_value = ({456: [1001]}, {1000}, [("Miles Davis", "Kind of Blue", 456)])
        runner = CliRunner()
        result = runner.invoke(main, ["collection", "remove", "--release-id", "456"])

        assert result.exit_code == 2
        mock_remove.assert_not_called()
        mock_invalidate.assert_not_called()


def _instance_item(release_id, instance_id, folder_id=1, rating=0, notes=None, title="The Dreaming"):
    item = MagicMock()
    item.data = {
        "id": release_id, "instance_id": instance_id, "folder_id": folder_id,
        "rating": rating, "notes": notes or [],
        "basic_information": {"title": title, "artists": [{"name": "Kate Bush"}]},
    }
    return item


def _collection_client(items):
    client = MagicMock()
    client._base_url = "https://api.discogs.com"
    me = client.identity.return_value
    me.username = "khaney"
    me.collection_folders.__getitem__.return_value.releases.page.side_effect = lambda p: items if p == 1 else []
    return client


OLD_INSTANCE = {
    "release_id": 9697557, "instance_id": 2124303711, "folder_id": 1, "rating": 3,
    "notes": [{"field_id": 1, "value": "Near Mint (NM or M-)"}, {"field_id": 3, "value": "Small seam split"}],
    "artist": "Kate Bush", "title": "The Dreaming",
}
NEW_RELEASE = {"release_id": 29576638, "artist": "Kate Bush", "title": "The Dreaming (The Escapologist Edition)"}


@patch("discogs_sync.sync_collection._remove_from_collection")
@patch("discogs_sync.sync_collection._copy_instance_metadata")
@patch("discogs_sync.sync_collection._add_instance", return_value=555)
@patch("discogs_sync.sync_collection._describe_remote_release", return_value=NEW_RELEASE)
@patch("discogs_sync.sync_collection._find_instance", return_value=OLD_INSTANCE)
class TestReplaceInCollection:
    def test_unconfirmed_previews_without_changes(self, _find, _describe, mock_add, mock_copy, mock_remove):
        from discogs_sync.exceptions import ConfirmationRequiredError

        with pytest.raises(ConfirmationRequiredError) as exc:
            replace_in_collection(MagicMock(), 29576638, old_release_id=9697557)

        preview = exc.value.preview
        assert preview["action"] == "replace"
        assert preview["old"]["instance_id"] == 2124303711
        assert preview["new"]["release_id"] == 29576638
        assert preview["notes"] == OLD_INSTANCE["notes"]
        assert preview["rating"] == 3
        mock_add.assert_not_called()
        mock_copy.assert_not_called()
        mock_remove.assert_not_called()

    def test_confirmed_adds_copies_then_removes(self, _find, _describe, mock_add, mock_copy, mock_remove):
        calls = MagicMock()
        calls.attach_mock(mock_add, "add")
        calls.attach_mock(mock_copy, "copy")
        calls.attach_mock(mock_remove, "remove")

        actions = replace_in_collection(MagicMock(), 29576638, instance_id=2124303711, confirm=True)

        assert [c[0] for c in calls.mock_calls] == ["add", "copy", "remove"]
        assert mock_add.call_args.args[1:3] == (29576638, 1)
        assert mock_copy.call_args.args[1:6] == (1, 29576638, 555, 3, OLD_INSTANCE["notes"])
        assert mock_remove.call_args.args[1:3] == (9697557, 2124303711)
        assert [a.action for a in actions] == [SyncActionType.ADD, SyncActionType.REMOVE]
        assert actions[0].release_id == 29576638
        assert actions[1].release_id == 9697557

    def test_copy_failure_keeps_old_instance(self, _find, _describe, mock_add, mock_copy, mock_remove):
        from discogs_sync.exceptions import SyncError

        mock_copy.side_effect = RuntimeError("boom")

        with pytest.raises(SyncError, match="NOT removed"):
            replace_in_collection(MagicMock(), 29576638, instance_id=2124303711, confirm=True)

        mock_remove.assert_not_called()

    def test_same_release_refused(self, _find, _describe, mock_add, mock_copy, mock_remove):
        from discogs_sync.exceptions import SyncError

        with pytest.raises(SyncError, match="already release"):
            replace_in_collection(MagicMock(), 9697557, instance_id=2124303711, confirm=True)

        mock_add.assert_not_called()


class TestFindInstance:
    def test_by_release_id_drops_empty_notes(self):
        client = _collection_client([
            _instance_item(111, 1, rating=4, notes=[{"field_id": 1, "value": "Mint (M)"}, {"field_id": 3, "value": ""}]),
            _instance_item(222, 2),
        ])

        found = _find_instance(client, MagicMock(), release_id=111)

        assert found["instance_id"] == 1
        assert found["rating"] == 4
        assert found["notes"] == [{"field_id": 1, "value": "Mint (M)"}]
        assert found["artist"] == "Kate Bush"

    def test_by_instance_id(self):
        client = _collection_client([_instance_item(111, 1), _instance_item(111, 2, folder_id=7)])

        found = _find_instance(client, MagicMock(), instance_id=2)

        assert found["instance_id"] == 2
        assert found["folder_id"] == 7

    def test_multiple_copies_requires_instance_id(self):
        from discogs_sync.exceptions import SyncError

        client = _collection_client([_instance_item(111, 1), _instance_item(111, 2)])

        with pytest.raises(SyncError, match="--instance-id"):
            _find_instance(client, MagicMock(), release_id=111)

    def test_not_in_collection(self):
        from discogs_sync.exceptions import SyncError

        with pytest.raises(SyncError, match="not in the collection"):
            _find_instance(_collection_client([]), MagicMock(), release_id=111)


class TestInstanceWrites:
    def test_add_instance_returns_new_instance_id(self):
        client = _collection_client([])
        client._post.return_value = {"instance_id": 999, "resource_url": "..."}

        assert _add_instance(client, 29576638, 1, MagicMock()) == 999
        client._post.assert_called_once_with(
            "https://api.discogs.com/users/khaney/collection/folders/1/releases/29576638", None,
        )

    def test_copy_metadata_sets_rating_and_fields(self):
        client = _collection_client([])
        notes = [{"field_id": 1, "value": "Very Good Plus (VG+)"}]

        _copy_instance_metadata(client, 1, 29576638, 999, 3, notes, MagicMock())

        base = "https://api.discogs.com/users/khaney/collection/folders/1/releases/29576638/instances/999"
        assert client._post.call_args_list[0].args == (base, {"rating": 3})
        assert client._post.call_args_list[1].args == (f"{base}/fields/1", {"value": "Very Good Plus (VG+)"})

    def test_copy_metadata_skips_zero_rating(self):
        client = _collection_client([])

        _copy_instance_metadata(client, 1, 29576638, 999, 0, [], MagicMock())

        client._post.assert_not_called()


class TestCollectionReplaceCli:
    @patch("discogs_sync.cache.invalidate_cache")
    @patch("discogs_sync.sync_collection._remove_from_collection")
    @patch("discogs_sync.sync_collection._add_instance")
    @patch("discogs_sync.sync_collection._describe_remote_release", return_value=NEW_RELEASE)
    @patch("discogs_sync.sync_collection._find_instance", return_value=OLD_INSTANCE)
    @patch("discogs_sync.client_factory.build_client")
    def test_without_yes_exits_2_with_preview(self, _client, _find, _describe, mock_add, mock_remove, mock_invalidate):
        result = CliRunner().invoke(main, [
            "collection", "replace", "--release-id", "29576638", "--old-release-id", "9697557",
            "--output-format", "json",
        ])

        assert result.exit_code == 2
        preview = json.loads(result.output[result.output.index("{"):])
        assert preview["confirmation_required"] is True
        assert preview["new"]["release_id"] == 29576638
        mock_add.assert_not_called()
        mock_remove.assert_not_called()
        mock_invalidate.assert_not_called()

    @patch("discogs_sync.cache.invalidate_cache")
    @patch("discogs_sync.sync_collection.replace_in_collection")
    @patch("discogs_sync.client_factory.build_client")
    def test_with_yes_confirms_and_invalidates_cache(self, _client, mock_replace, mock_invalidate):
        from discogs_sync.models import SyncAction
        mock_replace.return_value = [
            SyncAction(action=SyncActionType.ADD, release_id=29576638),
            SyncAction(action=SyncActionType.REMOVE, release_id=9697557),
        ]

        result = CliRunner().invoke(main, [
            "collection", "replace", "--release-id", "29576638", "--instance-id", "2124303711", "--yes",
        ])

        assert result.exit_code == 0
        assert mock_replace.call_args.kwargs["confirm"] is True
        assert mock_replace.call_args.kwargs["instance_id"] == 2124303711
        mock_invalidate.assert_called_once_with("collection")

    def test_requires_old_identifier(self):
        result = CliRunner().invoke(main, ["collection", "replace", "--release-id", "29576638"])
        assert result.exit_code == 2

    @patch("discogs_sync.cache.invalidate_cache")
    @patch("discogs_sync.sync_collection.replace_in_collection")
    @patch("discogs_sync.client_factory.build_client")
    def test_partial_failure_exits_2_and_invalidates_cache(self, _client, mock_replace, mock_invalidate):
        from discogs_sync.exceptions import SyncError
        mock_replace.side_effect = SyncError("copying rating/notes failed. The old instance 1 was NOT removed.")

        result = CliRunner().invoke(main, [
            "collection", "replace", "--release-id", "29576638", "--instance-id", "1", "--yes",
        ])

        assert result.exit_code == 2
        mock_invalidate.assert_called_once_with("collection")


def test_describe_remote_release_fetches_full_release():
    from discogs_sync.sync_collection import _describe_remote_release

    client = MagicMock()
    client.release.return_value.data = {"title": "The Dreaming", "artists": [{"name": "Kate Bush"}]}

    assert _describe_remote_release(client, 29576638, MagicMock()) == {
        "release_id": 29576638, "artist": "Kate Bush", "title": "The Dreaming",
    }
    client.release.return_value.refresh.assert_called_once()
