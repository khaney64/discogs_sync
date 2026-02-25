"""Tests for marketplace search caching."""

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from discogs_sync.cache import marketplace_cache_name, marketplace_resolve_cache_name
from discogs_sync.cli import main
from discogs_sync.models import MarketplaceResult


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_RESULTS = [
    MarketplaceResult(
        master_id=3425,
        release_id=7890,
        title="OK Computer",
        artist="Radiohead",
        format="Vinyl",
        country="UK",
        year=1997,
        num_for_sale=5,
        lowest_price=25.0,
        currency="USD",
    ),
]

SAMPLE_DICTS = [r.to_dict() for r in SAMPLE_RESULTS]


def _expected_name(cache_type: str, *key_parts) -> str:
    raw = "|".join(str(p) for p in key_parts)
    digest = hashlib.md5(raw.encode()).hexdigest()[:16]
    return f"marketplace_{cache_type}_{digest}"


# ---------------------------------------------------------------------------
# marketplace_cache_name unit tests
# ---------------------------------------------------------------------------

class TestMarketplaceCacheName:
    def test_release_type_format(self):
        name = marketplace_cache_name("release", 7890, "USD")
        assert name.startswith("marketplace_release_")
        assert len(name) > len("marketplace_release_")

    def test_master_type_format(self):
        name = marketplace_cache_name("master", 3425, "Vinyl", "US", "USD", 25)
        assert name.startswith("marketplace_master_")

    def test_artist_type_format(self):
        name = marketplace_cache_name("artist", "Radiohead", "OK Computer", None, None, "USD", 25, 0.7)
        assert name.startswith("marketplace_artist_")

    def test_same_inputs_produce_same_name(self):
        a = marketplace_cache_name("master", 3425, "Vinyl", "US", "USD", 25)
        b = marketplace_cache_name("master", 3425, "Vinyl", "US", "USD", 25)
        assert a == b

    def test_different_inputs_produce_different_names(self):
        a = marketplace_cache_name("master", 3425, "Vinyl", "US", "USD", 25)
        b = marketplace_cache_name("master", 3425, "CD", "US", "USD", 25)
        assert a != b

    def test_different_types_produce_different_names_even_same_parts(self):
        a = marketplace_cache_name("release", 3425, "USD")
        b = marketplace_cache_name("master", 3425, "USD")
        assert a != b

    def test_artist_only_uses_empty_album(self):
        """When album is absent, empty string is used so key is still deterministic."""
        a = marketplace_cache_name("artist", "Radiohead", "", None, None, "USD", 25, 0.7)
        b = marketplace_cache_name("artist", "Radiohead", "", None, None, "USD", 25, 0.7)
        assert a == b

    def test_details_flag_does_not_change_base_name(self):
        """details is NOT part of the base cache key — both requests share the same base entry."""
        base_with = marketplace_cache_name("master", 3425, None, None, "USD", 25)
        base_without = marketplace_cache_name("master", 3425, None, None, "USD", 25)
        assert base_with == base_without

    def test_name_matches_expected_hash(self):
        name = marketplace_cache_name("release", 7890, "USD")
        assert name == _expected_name("release", 7890, "USD")


# ---------------------------------------------------------------------------
# MarketplaceResult round-trip
# ---------------------------------------------------------------------------

class TestMarketplaceResultFromDict:
    def test_round_trip_full(self):
        original = MarketplaceResult(
            master_id=3425, release_id=7890, title="OK Computer",
            artist="Radiohead", format="Vinyl", country="UK",
            year=1997, num_for_sale=5, lowest_price=25.0, currency="USD",
            price_suggestions={"Near Mint (NM or M-)": 40.0},
            label="Parlophone", catno="NODATA42", format_details="180g",
            community_have=1500, community_want=800,
        )
        assert MarketplaceResult.from_dict(original.to_dict()) == original

    def test_round_trip_minimal(self):
        original = MarketplaceResult(release_id=7890, num_for_sale=0, currency="USD")
        assert MarketplaceResult.from_dict(original.to_dict()) == original

    def test_optional_fields_default_to_none(self):
        r = MarketplaceResult.from_dict({"num_for_sale": 0, "currency": "USD"})
        assert r.master_id is None
        assert r.price_suggestions is None
        assert r.label is None


# ---------------------------------------------------------------------------
# CLI cache behaviour — release_id
# ---------------------------------------------------------------------------

class TestMarketplaceCacheRelease:
    def test_cache_hit_skips_search_marketplace(self):
        """Cache hit → search_marketplace is not called."""
        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS) as mock_search, \
             patch("discogs_sync.cache.read_cache", return_value=SAMPLE_DICTS), \
             patch("discogs_sync.cache.write_cache") as mock_write, \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            result = runner.invoke(main, ["marketplace", "search", "--release-id", "7890", "--output-format", "json"])
        assert result.exit_code == 0
        mock_search.assert_not_called()
        mock_write.assert_not_called()

    def test_cache_miss_calls_search_and_writes(self):
        """Cache miss → search_marketplace called, write_cache called."""
        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS) as mock_search, \
             patch("discogs_sync.cache.read_cache", return_value=None), \
             patch("discogs_sync.cache.write_cache") as mock_write, \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            result = runner.invoke(main, ["marketplace", "search", "--release-id", "7890", "--output-format", "json"])
        assert result.exit_code == 0
        mock_search.assert_called_once()
        mock_write.assert_called_once()

    def test_no_cache_bypasses_read_but_writes(self):
        """--no-cache → read_cache skipped, search_marketplace called, write_cache called."""
        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS) as mock_search, \
             patch("discogs_sync.cache.read_cache") as mock_read, \
             patch("discogs_sync.cache.write_cache") as mock_write, \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            result = runner.invoke(main, ["marketplace", "search", "--release-id", "7890", "--no-cache", "--output-format", "json"])
        assert result.exit_code == 0
        mock_read.assert_not_called()
        mock_search.assert_called_once()
        mock_write.assert_called_once()

    def test_correct_cache_name_used_for_release(self):
        """Cache name for --release-id lookup uses the release cache type."""
        captured_names = []

        def fake_read(name):
            captured_names.append(name)
            return None

        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS), \
             patch("discogs_sync.cache.read_cache", side_effect=fake_read), \
             patch("discogs_sync.cache.write_cache"), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--release-id", "7890", "--output-format", "json"])

        assert len(captured_names) == 1
        assert captured_names[0].startswith("marketplace_release_")
        assert captured_names[0] == _expected_name("release", 7890, "USD")

    def test_cache_hit_output_matches_cached_data(self):
        """Cache hit serves the cached items correctly."""
        with patch("discogs_sync.cache.read_cache", return_value=SAMPLE_DICTS), \
             patch("discogs_sync.cache.write_cache"), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            result = runner.invoke(main, ["marketplace", "search", "--release-id", "7890", "--output-format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        items = data["results"]
        assert len(items) == 1
        assert items[0]["release_id"] == 7890
        assert items[0]["artist"] == "Radiohead"


# ---------------------------------------------------------------------------
# CLI cache behaviour — master_id
# ---------------------------------------------------------------------------

class TestMarketplaceCacheMaster:
    def test_correct_cache_name_for_master(self):
        captured_names = []

        def fake_read(name):
            captured_names.append(name)
            return None

        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS), \
             patch("discogs_sync.cache.read_cache", side_effect=fake_read), \
             patch("discogs_sync.cache.write_cache"), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--master-id", "3425", "--output-format", "json"])

        assert len(captured_names) == 1
        assert captured_names[0].startswith("marketplace_master_")
        assert captured_names[0] == _expected_name("master", 3425, None, None, "USD", 25)

    def test_format_and_country_in_key(self):
        """Same master-id with different format/country should use different cache entries."""
        name_vinyl = marketplace_cache_name("master", 3425, "Vinyl", "US", "USD", 25)
        name_cd = marketplace_cache_name("master", 3425, "CD", "US", "USD", 25)
        name_de = marketplace_cache_name("master", 3425, "Vinyl", "DE", "USD", 25)
        assert name_vinyl != name_cd
        assert name_vinyl != name_de

    def test_max_versions_in_key(self):
        a = marketplace_cache_name("master", 3425, None, None, "USD", 10)
        b = marketplace_cache_name("master", 3425, None, None, "USD", 50)
        assert a != b

    def test_release_id_with_master_id_uses_master_cache(self):
        """When both --master-id and --release-id are given, master cache type is used."""
        captured_names = []

        def fake_read(name):
            captured_names.append(name)
            return None

        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS), \
             patch("discogs_sync.cache.read_cache", side_effect=fake_read), \
             patch("discogs_sync.cache.write_cache"), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--master-id", "3425", "--release-id", "7890", "--output-format", "json"])

        assert captured_names[0].startswith("marketplace_master_")


# ---------------------------------------------------------------------------
# CLI cache behaviour — artist + album
# ---------------------------------------------------------------------------

class TestMarketplaceCacheArtistAlbum:
    def test_correct_cache_name_for_artist_album(self):
        """Artist+album search should write cache under marketplace_master_ key
        (resolved from results), not marketplace_artist_. Also writes a
        resolution cache entry."""
        written_names = []

        def fake_write(name, items):
            written_names.append(name)

        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS), \
             patch("discogs_sync.cache.read_cache", return_value=None), \
             patch("discogs_sync.cache.write_cache", side_effect=fake_write), \
             patch("discogs_sync.cache.read_resolve_cache", return_value=None), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--artist", "Radiohead", "--album", "OK Computer", "--output-format", "json"])

        # Should write: resolution cache + marketplace_master_ base cache
        marketplace_writes = [n for n in written_names if n.startswith("marketplace_master_")]
        resolve_writes = [n for n in written_names if n.startswith("marketplace_resolve_")]
        assert len(marketplace_writes) == 1
        assert marketplace_writes[0] == _expected_name("master", SAMPLE_RESULTS[0].master_id, None, None, "USD", 25)
        assert len(resolve_writes) == 1

    def test_threshold_in_resolve_key(self):
        """Different thresholds should produce different resolution cache keys."""
        a = marketplace_resolve_cache_name("Radiohead", "OK Computer", 0.7)
        b = marketplace_resolve_cache_name("Radiohead", "OK Computer", 0.9)
        assert a != b

    def test_artist_album_resolution_cache_hit_uses_master_key(self):
        """When resolution cache has a master_id, marketplace read uses master key."""
        resolved = {"master_id": 3425, "release_id": 7890}
        expected_base = _expected_name("master", 3425, None, None, "USD", 25)
        read_names = []

        def fake_read(name):
            read_names.append(name)
            if name == expected_base:
                return SAMPLE_DICTS
            return None

        with patch("discogs_sync.marketplace.search_marketplace") as mock_search, \
             patch("discogs_sync.cache.read_cache", side_effect=fake_read), \
             patch("discogs_sync.cache.write_cache"), \
             patch("discogs_sync.cache.read_resolve_cache", return_value=resolved), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            result = runner.invoke(main, ["marketplace", "search", "--artist", "Radiohead", "--album", "OK Computer", "--output-format", "json"])

        assert result.exit_code == 0
        mock_search.assert_not_called()
        assert expected_base in read_names

    def test_master_id_and_artist_album_share_cache(self):
        """After an artist+album search caches under master key, a subsequent
        --master-id search should hit that same cache entry."""
        mid = SAMPLE_RESULTS[0].master_id
        expected_base = _expected_name("master", mid, None, None, "USD", 25)

        # Simulate: artist+album wrote to this key → now master-id reads it
        read_names = []

        def fake_read(name):
            read_names.append(name)
            if name == expected_base:
                return SAMPLE_DICTS
            return None

        with patch("discogs_sync.marketplace.search_marketplace") as mock_search, \
             patch("discogs_sync.cache.read_cache", side_effect=fake_read), \
             patch("discogs_sync.cache.write_cache"), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            result = runner.invoke(main, ["marketplace", "search", "--master-id", str(mid), "--output-format", "json"])

        assert result.exit_code == 0
        mock_search.assert_not_called()
        assert expected_base in read_names

    def test_artist_album_fallback_to_release_cache(self):
        """When results have no master_id, artist+album should cache under release key."""
        release_only_results = [
            MarketplaceResult(
                master_id=None, release_id=7890, title="OK Computer",
                artist="Radiohead", format="Vinyl", country="UK",
                year=1997, num_for_sale=5, lowest_price=25.0, currency="USD",
            ),
        ]
        written_names = []

        def fake_write(name, items):
            written_names.append(name)

        with patch("discogs_sync.marketplace.search_marketplace", return_value=release_only_results), \
             patch("discogs_sync.cache.read_cache", return_value=None), \
             patch("discogs_sync.cache.write_cache", side_effect=fake_write), \
             patch("discogs_sync.cache.read_resolve_cache", return_value=None), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--artist", "Radiohead", "--album", "OK Computer", "--output-format", "json"])

        release_writes = [n for n in written_names if n.startswith("marketplace_release_")]
        assert len(release_writes) == 1
        assert release_writes[0] == _expected_name("release", 7890, "USD")

    def test_no_cache_skips_resolution_read_but_writes(self):
        """--no-cache skips resolution cache read, but still writes both
        resolution and marketplace caches."""
        written_names = []

        def fake_write(name, items):
            written_names.append(name)

        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS), \
             patch("discogs_sync.cache.read_cache") as mock_read, \
             patch("discogs_sync.cache.write_cache", side_effect=fake_write), \
             patch("discogs_sync.cache.read_resolve_cache") as mock_resolve_read, \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--artist", "Radiohead", "--album", "OK Computer", "--no-cache", "--output-format", "json"])

        mock_read.assert_not_called()
        mock_resolve_read.assert_not_called()
        # Should still write marketplace cache + resolution cache
        marketplace_writes = [n for n in written_names if n.startswith("marketplace_master_")]
        resolve_writes = [n for n in written_names if n.startswith("marketplace_resolve_")]
        assert len(marketplace_writes) == 1
        assert len(resolve_writes) == 1

    def test_empty_results_skip_cache_write(self):
        """When search returns no results, no cache write should happen."""
        written_names = []

        def fake_write(name, items):
            written_names.append(name)

        with patch("discogs_sync.marketplace.search_marketplace", return_value=[]), \
             patch("discogs_sync.cache.read_cache", return_value=None), \
             patch("discogs_sync.cache.write_cache", side_effect=fake_write), \
             patch("discogs_sync.cache.read_resolve_cache", return_value=None), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--artist", "Nobody", "--album", "Nothing", "--output-format", "json"])

        assert len(written_names) == 0


# ---------------------------------------------------------------------------
# Batch mode — no caching
# ---------------------------------------------------------------------------

class TestMarketplaceBatchNoCache:
    def test_batch_mode_does_not_read_or_write_cache(self, tmp_path):
        """Batch file mode must not touch the cache at all."""
        csv_file = tmp_path / "batch.csv"
        csv_file.write_text("artist,album\nRadiohead,OK Computer\n", encoding="utf-8")

        with patch("discogs_sync.marketplace.search_marketplace_batch", return_value=(SAMPLE_RESULTS, [])) as mock_batch, \
             patch("discogs_sync.cache.read_cache") as mock_read, \
             patch("discogs_sync.cache.write_cache") as mock_write, \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            result = runner.invoke(main, ["marketplace", "search", str(csv_file), "--output-format", "json"])

        assert result.exit_code == 0
        mock_batch.assert_called_once()
        mock_read.assert_not_called()
        mock_write.assert_not_called()


# ---------------------------------------------------------------------------
# Details cache split — separate base and details cache entries
# ---------------------------------------------------------------------------

SAMPLE_RESULTS_WITH_DETAILS = [
    MarketplaceResult(
        master_id=3425, release_id=7890, title="OK Computer", artist="Radiohead",
        format="Vinyl", country="UK", year=1997, num_for_sale=5, lowest_price=25.0,
        currency="USD", price_suggestions={"Near Mint (NM or M-)": 40.0},
    ),
]
SAMPLE_DICTS_WITH_DETAILS = [r.to_dict() for r in SAMPLE_RESULTS_WITH_DETAILS]
SAMPLE_DICTS_BASE = [{k: v for k, v in d.items() if k != "price_suggestions"} for d in SAMPLE_DICTS_WITH_DETAILS]


class TestMarketplaceDetailsCache:
    """Tests for the two-layer base / details caching."""

    def test_details_cache_hit_returns_price_suggestions_without_api_call(self):
        """Details cache hit → search_marketplace not called, price_suggestions present."""
        with patch("discogs_sync.marketplace.search_marketplace") as mock_search, \
             patch("discogs_sync.cache.read_cache", return_value=SAMPLE_DICTS_WITH_DETAILS), \
             patch("discogs_sync.cache.write_cache") as mock_write, \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            result = runner.invoke(main, ["marketplace", "search", "--master-id", "3425", "--details", "--output-format", "json"])
        assert result.exit_code == 0
        mock_search.assert_not_called()
        mock_write.assert_not_called()
        data = json.loads(result.output)
        assert data["results"][0]["price_suggestions"] is not None

    def test_details_miss_base_hit_fetches_only_suggestions(self):
        """Details cache miss + base cache hit → fetch_price_suggestions_for_results called."""
        details_name = marketplace_cache_name("master", 3425, None, None, "USD", 25) + "_details"
        call_count = {"n": 0}

        def fake_read(name):
            call_count["n"] += 1
            if name == details_name:
                return None  # details miss
            return SAMPLE_DICTS_BASE  # base hit

        with patch("discogs_sync.marketplace.search_marketplace") as mock_search, \
             patch("discogs_sync.marketplace.fetch_price_suggestions_for_results", return_value={7890: {"Near Mint (NM or M-)": 40.0}}) as mock_ps, \
             patch("discogs_sync.cache.read_cache", side_effect=fake_read), \
             patch("discogs_sync.cache.write_cache") as mock_write, \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            result = runner.invoke(main, ["marketplace", "search", "--master-id", "3425", "--details", "--output-format", "json"])
        assert result.exit_code == 0
        mock_search.assert_not_called()   # no full search needed
        mock_ps.assert_called_once()       # only price_suggestions fetched
        mock_write.assert_called_once()    # details cache written
        assert mock_write.call_args[0][0] == details_name

    def test_full_miss_with_details_writes_both_caches(self):
        """Both caches miss → full fetch, base cache and details cache both written."""
        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS_WITH_DETAILS), \
             patch("discogs_sync.cache.read_cache", return_value=None), \
             patch("discogs_sync.cache.write_cache") as mock_write, \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--master-id", "3425", "--details", "--output-format", "json"])
        assert mock_write.call_count == 2
        written_names = {call[0][0] for call in mock_write.call_args_list}
        base_name = marketplace_cache_name("master", 3425, None, None, "USD", 25)
        assert base_name in written_names
        assert f"{base_name}_details" in written_names

    def test_full_miss_base_written_without_price_suggestions(self):
        """When full fetch is done with --details, base cache must NOT contain price_suggestions."""
        written = {}

        def fake_write(name, items):
            written[name] = items

        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS_WITH_DETAILS), \
             patch("discogs_sync.cache.read_cache", return_value=None), \
             patch("discogs_sync.cache.write_cache", side_effect=fake_write), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--master-id", "3425", "--details"])

        base_name = marketplace_cache_name("master", 3425, None, None, "USD", 25)
        assert base_name in written
        for item in written[base_name]:
            assert "price_suggestions" not in item

    def test_no_details_request_uses_base_cache_hits(self):
        """Without --details, a prior --details write (which also wrote base) is reused."""
        with patch("discogs_sync.marketplace.search_marketplace") as mock_search, \
             patch("discogs_sync.cache.read_cache", return_value=SAMPLE_DICTS_BASE), \
             patch("discogs_sync.cache.write_cache"), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            result = runner.invoke(main, ["marketplace", "search", "--master-id", "3425", "--output-format", "json"])
        assert result.exit_code == 0
        mock_search.assert_not_called()

    def test_no_details_request_only_reads_base_cache(self):
        """Without --details, the details cache is never consulted."""
        captured_names = []

        def fake_read(name):
            captured_names.append(name)
            return None

        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS), \
             patch("discogs_sync.cache.read_cache", side_effect=fake_read), \
             patch("discogs_sync.cache.write_cache"), \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--master-id", "3425", "--output-format", "json"])

        assert len(captured_names) == 1
        assert not captured_names[0].endswith("_details")

    def test_no_cache_with_details_writes_both_and_skips_reads(self):
        """--no-cache --details: no reads, writes base + details."""
        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS_WITH_DETAILS), \
             patch("discogs_sync.cache.read_cache") as mock_read, \
             patch("discogs_sync.cache.write_cache") as mock_write, \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--master-id", "3425", "--details", "--no-cache"])
        mock_read.assert_not_called()
        assert mock_write.call_count == 2

    def test_no_cache_without_details_writes_base_only(self):
        """--no-cache without --details: no reads, writes base only."""
        with patch("discogs_sync.marketplace.search_marketplace", return_value=SAMPLE_RESULTS), \
             patch("discogs_sync.cache.read_cache") as mock_read, \
             patch("discogs_sync.cache.write_cache") as mock_write, \
             patch("discogs_sync.client_factory.build_client"):
            runner = CliRunner()
            runner.invoke(main, ["marketplace", "search", "--master-id", "3425", "--no-cache"])
        mock_read.assert_not_called()
        mock_write.assert_called_once()
        assert not mock_write.call_args[0][0].endswith("_details")
