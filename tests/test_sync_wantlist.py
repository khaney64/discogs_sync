"""Tests for wantlist sync operations."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from discogs_sync.cli import main
from discogs_sync.models import InputRecord, SyncActionType, WantlistItem
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
        mock_get_ids.return_value = (set(), set(), [])  # empty wantlist

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
        mock_get_ids.return_value = ({123}, {3425}, [("Radiohead", "OK Computer", 123)])  # already in wantlist

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
        mock_get_ids.return_value = (set(), set(), [])

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
        mock_get_ids.return_value = (set(), set(), [])

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
        mock_get_ids.return_value = ({123, 456}, {3425, 9999}, [("Radiohead", "OK Computer", 123), ("Pink Floyd", "Animals", 456)])  # 456 is extra

        client = MagicMock()
        report = sync_wantlist(client, [record], remove_extras=True, confirm_removals=True)

        assert report.removed == 1
        mock_remove.assert_called_once()


class TestRemoveExtrasGuards:
    @patch("discogs_sync.sync_wantlist._add_to_wantlist")
    @patch("discogs_sync.sync_wantlist._remove_from_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_unconfirmed_remove_extras_refused_before_changes(self, mock_search, mock_resolve, mock_get_ids, mock_remove, mock_add):
        from discogs_sync.exceptions import SyncError
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Radiohead", album="OK Computer")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=123, matched=True, score=0.9,
        )
        mock_resolve.return_value = 123
        mock_get_ids.return_value = ({456}, set(), [("Pink Floyd", "Animals", 456)])

        with pytest.raises(SyncError, match="would delete 1 item"):
            sync_wantlist(MagicMock(), [record], remove_extras=True)

        mock_remove.assert_not_called()
        mock_add.assert_not_called()

    @patch("discogs_sync.sync_wantlist._remove_from_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_unresolved_record_blocks_remove_extras(self, mock_search, mock_get_ids, mock_remove):
        from discogs_sync.exceptions import SyncError
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Pink Floyd", album="Animals (typo)")
        mock_search.return_value = SearchResult(input_record=record, matched=False, error="No match found")
        mock_get_ids.return_value = ({456}, set(), [("Pink Floyd", "Animals", 456)])

        with pytest.raises(SyncError, match="failed to resolve"):
            sync_wantlist(MagicMock(), [record], remove_extras=True, confirm_removals=True)

        mock_remove.assert_not_called()

    @patch("discogs_sync.sync_wantlist._remove_from_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_dry_run_remove_extras_needs_no_confirmation(self, mock_search, mock_resolve, mock_get_ids, mock_remove):
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Radiohead", album="OK Computer")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=123, matched=True, score=0.9,
        )
        mock_resolve.return_value = 123
        mock_get_ids.return_value = ({123, 456}, set(), [("Radiohead", "OK Computer", 123), ("Pink Floyd", "Animals", 456)])

        report = sync_wantlist(MagicMock(), [record], remove_extras=True, dry_run=True)

        assert report.removed == 1
        mock_remove.assert_not_called()

    @patch("discogs_sync.sync_wantlist.sync_wantlist")
    @patch("discogs_sync.client_factory.build_client")
    def test_cli_yes_flag_passes_confirmation(self, _mock_client, mock_sync, tmp_csv):
        from discogs_sync.models import SyncReport

        mock_sync.return_value = SyncReport(total_input=0)
        runner = CliRunner()
        csv_path = tmp_csv("artist,album\nRadiohead,OK Computer\n")
        runner.invoke(main, ["wantlist", "sync", str(csv_path), "--remove-extras", "--yes"])

        assert mock_sync.call_args.kwargs["confirm_removals"] is True

    @patch("discogs_sync.sync_wantlist.sync_wantlist")
    @patch("discogs_sync.client_factory.build_client")
    def test_cli_refusal_exits_2(self, _mock_client, mock_sync, tmp_csv):
        from discogs_sync.exceptions import SyncError

        mock_sync.side_effect = SyncError("--remove-extras would delete 3 item(s).")
        runner = CliRunner()
        csv_path = tmp_csv("artist,album\nRadiohead,OK Computer\n")
        result = runner.invoke(main, ["wantlist", "sync", str(csv_path), "--remove-extras"])

        assert result.exit_code == 2
        assert mock_sync.call_args.kwargs["confirm_removals"] is False


class TestAddToWantlist:
    @patch("discogs_sync.sync_wantlist._add_to_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    def test_add_by_release_id(self, mock_get_ids, mock_add):
        """Adding by release_id directly."""
        mock_get_ids.return_value = (set(), set(), [])
        client = MagicMock()

        action = add_to_wantlist(client, release_id=123)

        assert action.action == SyncActionType.ADD
        assert action.release_id == 123

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    def test_skip_duplicate(self, mock_get_ids):
        """Should skip if already in wantlist."""
        mock_get_ids.return_value = ({123}, {3425}, [("Radiohead", "OK Computer", 123)])
        client = MagicMock()

        action = add_to_wantlist(client, release_id=123)

        assert action.action == SyncActionType.SKIP
        assert "Already in wantlist" in action.reason


class TestRemoveFromWantlist:
    @patch("discogs_sync.sync_wantlist._remove_from_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    def test_remove_existing(self, mock_get_ids, mock_remove):
        """Removing an item that exists."""
        mock_get_ids.return_value = ({123}, {3425}, [("Radiohead", "OK Computer", 123)])
        client = MagicMock()

        action = remove_from_wantlist(client, release_id=123, confirm=True)

        assert action.action == SyncActionType.REMOVE
        assert (action.artist, action.title) == ("Radiohead", "OK Computer")
        mock_remove.assert_called_once()

    @patch("discogs_sync.sync_wantlist._remove_from_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    def test_unconfirmed_remove_previews_without_removing(self, mock_get_ids, mock_remove):
        from discogs_sync.exceptions import ConfirmationRequiredError

        mock_get_ids.return_value = ({123}, {3425}, [("Radiohead", "OK Computer", 123)])

        with pytest.raises(ConfirmationRequiredError) as exc:
            remove_from_wantlist(MagicMock(), release_id=123)

        assert exc.value.preview == {
            "action": "remove", "target": "wantlist",
            "release_id": 123, "artist": "Radiohead", "title": "OK Computer",
        }
        mock_remove.assert_not_called()

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    def test_remove_nonexistent(self, mock_get_ids):
        """Removing an item not in wantlist should skip."""
        mock_get_ids.return_value = (set(), set(), [])
        client = MagicMock()

        action = remove_from_wantlist(client, release_id=123)

        assert action.action == SyncActionType.SKIP
        assert "Not in wantlist" in action.reason


class TestMasterIdMatching:
    """Tests for master_id-based duplicate detection in wantlist sync."""

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_skip_when_different_pressing_in_wantlist(self, mock_search, mock_resolve, mock_get_ids):
        """Different release_id but same master_id should SKIP."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Radiohead", album="OK Computer")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=123, master_id=3425,
            title="OK Computer", artist="Radiohead", matched=True, score=0.9,
        )
        mock_resolve.return_value = 123
        # Wantlist has release_id=999 (different pressing) but same master_id=3425
        mock_get_ids.return_value = ({999}, {3425}, [("Radiohead", "OK Computer", 999)])

        client = MagicMock()
        report = sync_wantlist(client, [record])

        assert report.skipped == 1
        assert report.added == 0

    @patch("discogs_sync.sync_wantlist._add_to_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_add_when_no_master_id_match(self, mock_search, mock_resolve, mock_get_ids, mock_add):
        """Different release_id and different master_id should ADD."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Radiohead", album="OK Computer")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=123, master_id=3425,
            title="OK Computer", artist="Radiohead", matched=True, score=0.9,
        )
        mock_resolve.return_value = 123
        # Wantlist has a completely different master and different artist/title
        mock_get_ids.return_value = ({999}, {8888}, [("Pink Floyd", "Animals", 999)])

        client = MagicMock()
        report = sync_wantlist(client, [record])

        assert report.added == 1
        assert report.skipped == 0
        mock_add.assert_called_once()

    @patch("discogs_sync.sync_wantlist._add_to_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_add_when_result_has_no_master_id(self, mock_search, mock_resolve, mock_get_ids, mock_add):
        """When search result has no master_id and no fuzzy match, should ADD."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Radiohead", album="OK Computer")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=123, master_id=None,
            title="OK Computer", artist="Radiohead", matched=True, score=0.9,
        )
        mock_resolve.return_value = 123
        # Wantlist has a different album entirely (no release_id, master_id, or fuzzy match)
        mock_get_ids.return_value = ({999}, {3425}, [("Pink Floyd", "Animals", 999)])

        client = MagicMock()
        report = sync_wantlist(client, [record])

        assert report.added == 1
        assert report.skipped == 0

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    def test_add_to_wantlist_skip_by_master_id(self, mock_get_ids):
        """add_to_wantlist should skip when master_id matches even if release_id differs."""
        # Wantlist has release 999 with master 3425
        mock_get_ids.return_value = ({999}, {3425}, [("Radiohead", "OK Computer", 999)])
        client = MagicMock()

        action = add_to_wantlist(client, release_id=123, master_id=3425)

        assert action.action == SyncActionType.SKIP
        assert "Already in wantlist" in action.reason


class TestFuzzyMatching:
    """Tests for fuzzy artist+title duplicate detection in wantlist sync."""

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_skip_fuzzy_match_different_release_no_master(self, mock_search, mock_resolve, mock_get_ids):
        """Different release_id, no master_id, but matching artist+title should SKIP via fuzzy match."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="The Alan Parsons Project", album="I Robot")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, master_id=None,
            title="I Robot", artist="The Alan Parsons Project", matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        mock_get_ids.return_value = ({789}, set(), [("The Alan Parsons Project", "I Robot", 789)])

        client = MagicMock()
        report = sync_wantlist(client, [record])

        assert report.skipped == 1
        assert report.added == 0
        assert "fuzzy match" in report.actions[0].reason

    @patch("discogs_sync.sync_wantlist._add_to_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_add_when_no_fuzzy_match(self, mock_search, mock_resolve, mock_get_ids, mock_add):
        """Different release_id, no master_id, different artist+title should ADD."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Supertramp", album="Breakfast In America")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, master_id=None,
            title="Breakfast In America", artist="Supertramp", matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        mock_get_ids.return_value = ({789}, set(), [("Pink Floyd", "Dark Side of the Moon", 789)])

        client = MagicMock()
        report = sync_wantlist(client, [record])

        assert report.added == 1
        assert report.skipped == 0
        mock_add.assert_called_once()

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.sync_wantlist.resolve_to_release_id")
    @patch("discogs_sync.sync_wantlist.search_release")
    def test_skip_fuzzy_match_slight_title_variation(self, mock_search, mock_resolve, mock_get_ids):
        """Slight title case variation should still fuzzy match and SKIP."""
        from discogs_sync.models import SearchResult

        record = InputRecord(artist="Supertramp", album="Breakfast in America")
        mock_search.return_value = SearchResult(
            input_record=record, release_id=456, master_id=None,
            title="Breakfast in America", artist="Supertramp", matched=True, score=0.9,
        )
        mock_resolve.return_value = 456
        mock_get_ids.return_value = ({789}, set(), [("Supertramp", "Breakfast In America", 789)])

        client = MagicMock()
        report = sync_wantlist(client, [record])

        assert report.skipped == 1
        assert report.added == 0
        assert "fuzzy match" in report.actions[0].reason

    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    def test_add_to_wantlist_skip_by_fuzzy_match(self, mock_get_ids):
        """add_to_wantlist should skip via fuzzy match when release_id/master_id don't match."""
        mock_get_ids.return_value = ({789}, set(), [("Quincy Jones", "The Dude", 789)])
        client = MagicMock()

        action = add_to_wantlist(client, release_id=456, artist="Quincy Jones", album="The Dude")

        assert action.action == SyncActionType.SKIP
        assert "fuzzy match" in action.reason


class TestWantlistListSearch:
    """Tests for wantlist list --search filtering."""

    ITEMS = [
        WantlistItem(release_id=1, artist="Radiohead", title="OK Computer"),
        WantlistItem(release_id=2, artist="Miles Davis", title="Kind of Blue"),
        WantlistItem(release_id=3, artist="Radiohead", title="Kid A"),
    ]

    @pytest.fixture(autouse=True)
    def patch_cache(self):
        """Prevent real cache reads/writes during list command tests."""
        with patch("discogs_sync.cache.read_cache", return_value=None), \
             patch("discogs_sync.cache.write_cache"):
            yield

    @patch("discogs_sync.sync_wantlist.list_wantlist", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_search_matches_artist(self, _mock_client, _mock_list):
        """--search should filter by artist name."""
        runner = CliRunner()
        result = runner.invoke(main, ["wantlist", "list", "--search", "radiohead", "--output-format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 2
        artists = {i["artist"] for i in data["items"]}
        assert artists == {"Radiohead"}

    @patch("discogs_sync.sync_wantlist.list_wantlist", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_search_matches_title(self, _mock_client, _mock_list):
        """--search should filter by title."""
        runner = CliRunner()
        result = runner.invoke(main, ["wantlist", "list", "--search", "kind of blue", "--output-format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Kind of Blue"

    @patch("discogs_sync.sync_wantlist.list_wantlist", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_search_no_matches(self, _mock_client, _mock_list):
        """--search with no matches returns empty list."""
        runner = CliRunner()
        result = runner.invoke(main, ["wantlist", "list", "--search", "beatles", "--output-format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 0
        assert data["items"] == []

    @patch("discogs_sync.sync_wantlist.list_wantlist", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_no_search_returns_all(self, _mock_client, _mock_list):
        """Without --search, all items are returned."""
        runner = CliRunner()
        result = runner.invoke(main, ["wantlist", "list", "--output-format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 3

    @patch("discogs_sync.sync_wantlist.list_wantlist", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_cache_hit_skips_api(self, _mock_client, mock_list):
        """When cache has a valid hit, list_wantlist should not be called."""
        cached_dicts = [i.to_dict() for i in self.ITEMS]
        with patch("discogs_sync.cache.read_cache", return_value=cached_dicts), \
             patch("discogs_sync.cache.write_cache") as mock_write:
            runner = CliRunner()
            result = runner.invoke(main, ["wantlist", "list", "--output-format", "json"])
        assert result.exit_code == 0
        mock_list.assert_not_called()
        mock_write.assert_not_called()
        data = json.loads(result.output)
        assert data["total"] == 3

    @patch("discogs_sync.sync_wantlist.list_wantlist", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_no_cache_flag_bypasses_read_but_writes(self, _mock_client, mock_list):
        """--no-cache forces API call and still updates the cache."""
        with patch("discogs_sync.cache.read_cache") as mock_read, \
             patch("discogs_sync.cache.write_cache") as mock_write:
            runner = CliRunner()
            result = runner.invoke(main, ["wantlist", "list", "--no-cache", "--output-format", "json"])
        assert result.exit_code == 0
        mock_read.assert_not_called()
        mock_list.assert_called_once()
        mock_write.assert_called_once()

    @patch("discogs_sync.sync_wantlist.list_wantlist", return_value=ITEMS)
    @patch("discogs_sync.client_factory.build_client")
    def test_cache_miss_calls_api_and_writes(self, _mock_client, mock_list):
        """On a cache miss, list_wantlist is called and result is written to cache."""
        with patch("discogs_sync.cache.read_cache", return_value=None), \
             patch("discogs_sync.cache.write_cache") as mock_write:
            runner = CliRunner()
            result = runner.invoke(main, ["wantlist", "list", "--output-format", "json"])
        assert result.exit_code == 0
        mock_list.assert_called_once()
        mock_write.assert_called_once()


class TestWantlistCacheInvalidation:
    """Tests that mutating wantlist commands invalidate the cache."""

    @patch("discogs_sync.cache.invalidate_cache")
    @patch("discogs_sync.sync_wantlist.add_to_wantlist")
    @patch("discogs_sync.client_factory.build_client")
    def test_add_invalidates_cache(self, _mock_client, mock_add, mock_invalidate):
        """wantlist add should call invalidate_cache('wantlist')."""
        from discogs_sync.models import SyncAction, SyncActionType
        mock_add.return_value = SyncAction(
            action=SyncActionType.ADD, release_id=123, artist="Radiohead", title="OK Computer",
        )
        runner = CliRunner()
        result = runner.invoke(main, ["wantlist", "add", "--release-id", "123"])
        assert result.exit_code == 0
        mock_invalidate.assert_called_once_with("wantlist")

    @patch("discogs_sync.cache.invalidate_cache")
    @patch("discogs_sync.sync_wantlist.remove_from_wantlist")
    @patch("discogs_sync.client_factory.build_client")
    def test_remove_invalidates_cache(self, _mock_client, mock_remove, mock_invalidate):
        """wantlist remove should call invalidate_cache('wantlist')."""
        from discogs_sync.models import SyncAction, SyncActionType
        mock_remove.return_value = SyncAction(
            action=SyncActionType.REMOVE, release_id=123, artist="Radiohead", title="OK Computer",
        )
        runner = CliRunner()
        result = runner.invoke(main, ["wantlist", "remove", "--release-id", "123", "--yes"])
        assert result.exit_code == 0
        assert mock_remove.call_args.kwargs["confirm"] is True
        mock_invalidate.assert_called_once_with("wantlist")

    @patch("discogs_sync.cache.invalidate_cache")
    @patch("discogs_sync.sync_wantlist._remove_from_wantlist")
    @patch("discogs_sync.sync_wantlist._get_wantlist_release_ids")
    @patch("discogs_sync.client_factory.build_client")
    def test_remove_without_yes_exits_2_with_json_preview(self, _mock_client, mock_get_ids, mock_remove, mock_invalidate):
        """wantlist remove without --yes refuses, previews the target, and changes nothing."""
        mock_get_ids.return_value = ({123}, {3425}, [("Radiohead", "OK Computer", 123)])
        runner = CliRunner()
        result = runner.invoke(main, ["wantlist", "remove", "--release-id", "123", "--output-format", "json"])

        assert result.exit_code == 2
        preview = json.loads(result.stdout)
        assert preview["confirmation_required"] is True
        assert preview["title"] == "OK Computer"
        mock_remove.assert_not_called()
        mock_invalidate.assert_not_called()
