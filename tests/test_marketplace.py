"""Tests for marketplace search."""

from unittest.mock import MagicMock, patch

import pytest

from discogs_sync.marketplace import search_marketplace, search_marketplace_batch
from discogs_sync.models import InputRecord, MarketplaceResult


def _mock_price_suggestions():
    """Create a mock PriceSuggestions object with named properties."""
    suggestions = MagicMock()
    for attr, value in [
        ("mint", 80.0),
        ("near_mint", 60.0),
        ("very_good_plus", 40.0),
        ("very_good", 25.0),
        ("good_plus", 15.0),
        ("good", 10.0),
        ("fair", 5.0),
        ("poor", 2.0),
    ]:
        price = MagicMock()
        price.value = value
        setattr(suggestions, attr, price)
    return suggestions


def _make_mock_release(data, stats=None, price_suggestions=None):
    """Create a mock release with fetch() support.

    The fetch() method is a no-op since mock .data is already populated,
    matching the real behavior where fetch() populates .data from the API.
    """
    mock_release = MagicMock()
    mock_release.data = data
    mock_release.id = data.get("id")
    mock_release.fetch = MagicMock(return_value=None)
    if stats is not None:
        mock_release.marketplace_stats = stats
    if price_suggestions is not None:
        mock_release.price_suggestions = price_suggestions
    return mock_release


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

        mock_stats = MagicMock()
        mock_stats.num_for_sale = 42
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 25.99

        mock_release = _make_mock_release(
            data={
                "id": 7890,
                "title": "OK Computer",
                "artists": [{"name": "Radiohead", "join": ""}],
                "formats": [{"name": "Vinyl"}],
                "country": "US",
                "year": 1997,
                "master_id": 3425,
            },
            stats=mock_stats,
        )

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

        results = search_marketplace(client, master_id=3425, max_versions=1)

        assert len(results) == 1
        assert results[0].artist == "Radiohead"
        assert results[0].title == "OK Computer"
        assert results[0].country == "US"
        assert results[0].year == 1997

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_country_filter(self, mock_api):
        """Country filter should exclude versions from non-matching countries."""
        mock_master = MagicMock()
        mock_us_version = MagicMock()
        mock_us_version.data = {
            "id": 1001,
            "title": "OK Computer",
            "format": "Vinyl",
            "country": "US",
            "year": 1997,
            "major_formats": ["Vinyl"],
        }
        mock_uk_version = MagicMock()
        mock_uk_version.data = {
            "id": 1002,
            "title": "OK Computer",
            "format": "Vinyl",
            "country": "UK",
            "year": 1997,
            "major_formats": ["Vinyl"],
        }

        mock_versions = MagicMock()
        mock_versions.page.side_effect = [[mock_us_version, mock_uk_version], []]

        mock_stats = MagicMock()
        mock_stats.num_for_sale = 10
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 30.0

        mock_release = _make_mock_release(
            data={
                "id": 1002,
                "title": "OK Computer",
                "artists": [{"name": "Radiohead", "join": ""}],
                "formats": [{"name": "Vinyl"}],
                "country": "UK",
                "year": 1997,
                "master_id": 3425,
            },
            stats=mock_stats,
        )

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.master.return_value = mock_master
        mock_master.versions = mock_versions
        client.release.return_value = mock_release

        results = search_marketplace(client, master_id=3425, country="UK", max_versions=5)

        assert len(results) == 1
        assert results[0].country == "UK"

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_country_filter_exact_match(self, mock_api):
        """Country filter 'US' should NOT match 'Australia' (exact match, not substring)."""
        mock_master = MagicMock()
        mock_au_version = MagicMock()
        mock_au_version.data = {
            "id": 2001,
            "title": "Crimes Of Passion",
            "format": "Vinyl",
            "country": "Australia",
            "year": 1980,
            "major_formats": ["Vinyl"],
        }
        mock_us_version = MagicMock()
        mock_us_version.data = {
            "id": 2002,
            "title": "Crimes Of Passion",
            "format": "Vinyl",
            "country": "US",
            "year": 1980,
            "major_formats": ["Vinyl"],
        }

        mock_versions = MagicMock()
        mock_versions.page.side_effect = [[mock_au_version, mock_us_version], []]

        mock_stats = MagicMock()
        mock_stats.num_for_sale = 12
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 8.35

        mock_release_us = _make_mock_release(
            data={
                "id": 2002,
                "title": "Crimes Of Passion",
                "artists": [{"name": "Pat Benatar", "join": ""}],
                "formats": [{"name": "Vinyl"}],
                "country": "US",
                "year": 1980,
                "master_id": 3250443,
            },
            stats=mock_stats,
        )

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.master.return_value = mock_master
        mock_master.versions = mock_versions
        client.release.return_value = mock_release_us

        results = search_marketplace(client, master_id=3250443, country="US", max_versions=5)

        # Should only match US, not Australia
        assert len(results) == 1
        assert results[0].country == "US"

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


class TestPriceSuggestions:
    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_details_true_populates_price_suggestions(self, mock_api):
        """details=True should populate price_suggestions dict."""
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

        mock_versions = MagicMock()
        mock_versions.page.return_value = [mock_version]

        mock_stats = MagicMock()
        mock_stats.num_for_sale = 42
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 25.99

        mock_release = _make_mock_release(
            data={
                "id": 7890,
                "title": "OK Computer",
                "artists": [{"name": "Radiohead", "join": ""}],
                "formats": [{"name": "Vinyl"}],
                "country": "US",
                "year": 1997,
                "master_id": 3425,
            },
            stats=mock_stats,
            price_suggestions=_mock_price_suggestions(),
        )

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.master.return_value = mock_master
        mock_master.versions = mock_versions
        client.release.return_value = mock_release

        results = search_marketplace(client, master_id=3425, max_versions=1, details=True)

        assert len(results) == 1
        ps = results[0].price_suggestions
        assert ps is not None
        assert ps["Near Mint (NM or M-)"] == 60.0
        assert ps["Very Good Plus (VG+)"] == 40.0
        assert ps["Very Good (VG)"] == 25.0
        assert ps["Mint (M)"] == 80.0

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_details_false_leaves_price_suggestions_none(self, mock_api):
        """details=False (default) should leave price_suggestions as None."""
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

        mock_versions = MagicMock()
        mock_versions.page.return_value = [mock_version]

        mock_stats = MagicMock()
        mock_stats.num_for_sale = 42
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 25.99

        mock_release = _make_mock_release(
            data={
                "id": 7890,
                "title": "OK Computer",
                "artists": [{"name": "Radiohead", "join": ""}],
                "formats": [{"name": "Vinyl"}],
                "country": "US",
                "year": 1997,
                "master_id": 3425,
            },
            stats=mock_stats,
        )

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.master.return_value = mock_master
        mock_master.versions = mock_versions
        client.release.return_value = mock_release

        results = search_marketplace(client, master_id=3425, max_versions=1, details=False)

        assert len(results) == 1
        assert results[0].price_suggestions is None

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_price_suggestions_api_failure_returns_none(self, mock_api):
        """Price suggestions API failure should return None gracefully."""
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

        mock_versions = MagicMock()
        mock_versions.page.return_value = [mock_version]

        mock_stats = MagicMock()
        mock_stats.num_for_sale = 42
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 25.99

        mock_release = _make_mock_release(
            data={
                "id": 7890,
                "title": "OK Computer",
                "artists": [{"name": "Radiohead", "join": ""}],
                "formats": [{"name": "Vinyl"}],
                "country": "US",
                "year": 1997,
                "master_id": 3425,
            },
            stats=mock_stats,
        )
        # Make price_suggestions raise an exception
        type(mock_release).price_suggestions = property(
            lambda self: (_ for _ in ()).throw(Exception("API error"))
        )

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.master.return_value = mock_master
        mock_master.versions = mock_versions
        client.release.return_value = mock_release

        results = search_marketplace(client, master_id=3425, max_versions=1, details=True)

        assert len(results) == 1
        assert results[0].price_suggestions is None


class TestReleaseFetch:
    """Tests verifying release.refresh() is called to populate full release data."""

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_fetch_called_for_version_releases(self, mock_api):
        """release.refresh() should be called to load artist/country/year data."""
        mock_master = MagicMock()
        mock_version = MagicMock()
        mock_version.data = {
            "id": 7890,
            "title": "OK Computer",
            "format": "Vinyl",
            "major_formats": ["Vinyl"],
        }

        mock_versions = MagicMock()
        mock_versions.page.return_value = [mock_version]

        mock_stats = MagicMock()
        mock_stats.num_for_sale = 10
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 20.0

        mock_release = _make_mock_release(
            data={
                "id": 7890,
                "title": "OK Computer",
                "artists": [{"name": "Radiohead", "join": ""}],
                "formats": [{"name": "Vinyl"}],
                "country": "UK",
                "year": 1997,
                "master_id": 3425,
            },
            stats=mock_stats,
        )

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.master.return_value = mock_master
        mock_master.versions = mock_versions
        client.release.return_value = mock_release

        results = search_marketplace(client, master_id=3425, max_versions=1)

        # Verify refresh was called on the release object
        mock_release.refresh.assert_called()
        assert len(results) == 1
        assert results[0].artist == "Radiohead"
        assert results[0].country == "UK"

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_fetch_called_for_single_release(self, mock_api):
        """_get_stats_for_release should also call refresh()."""
        from discogs_sync.marketplace import _get_stats_for_release
        from discogs_sync.rate_limiter import get_rate_limiter

        mock_stats = MagicMock()
        mock_stats.num_for_sale = 5
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 15.0

        mock_release = _make_mock_release(
            data={
                "id": 1234,
                "title": "Kid A",
                "artists": [{"name": "Radiohead", "join": ""}],
                "formats": [{"name": "CD"}],
                "country": "EU",
                "year": 2000,
                "master_id": 5678,
            },
            stats=mock_stats,
        )

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.release.return_value = mock_release

        limiter = get_rate_limiter()
        results = _get_stats_for_release(client, 1234, "USD", None, None, limiter)

        mock_release.refresh.assert_called()
        assert len(results) == 1
        assert results[0].artist == "Radiohead"
        assert results[0].country == "EU"
        assert results[0].year == 2000

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_verbose_logs_release_data(self, mock_api):
        """verbose=True should log release data details."""
        mock_master = MagicMock()
        mock_version = MagicMock()
        mock_version.data = {
            "id": 7890,
            "title": "OK Computer",
            "format": "Vinyl",
            "major_formats": ["Vinyl"],
        }

        mock_versions = MagicMock()
        mock_versions.page.return_value = [mock_version]

        mock_stats = MagicMock()
        mock_stats.num_for_sale = 10
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 20.0

        mock_release = _make_mock_release(
            data={
                "id": 7890,
                "title": "OK Computer",
                "artists": [{"name": "Radiohead", "join": ""}],
                "formats": [{"name": "Vinyl"}],
                "country": "US",
                "year": 1997,
                "master_id": 3425,
            },
            stats=mock_stats,
        )

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.master.return_value = mock_master
        mock_master.versions = mock_versions
        client.release.return_value = mock_release

        with patch("discogs_sync.marketplace.print_verbose") as mock_verbose:
            results = search_marketplace(client, master_id=3425, max_versions=1, verbose=True)

        assert len(results) == 1
        # Should have logged release data details
        verbose_calls = [str(c) for c in mock_verbose.call_args_list]
        assert any("Release 7890" in c for c in verbose_calls)
        assert any("artist=True" in c for c in verbose_calls)


class TestReleaseIdDirectLookup:
    """When --release-id is provided without --master-id, only that release should be returned."""

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_release_id_goes_directly_to_single_release(self, mock_api):
        """Providing release_id should NOT scan master versions."""
        mock_stats = MagicMock()
        mock_stats.num_for_sale = 174
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 1.25

        mock_release = _make_mock_release(
            data={
                "id": 665695,
                "title": "Crimes Of Passion",
                "artists": [{"name": "Pat Benatar", "join": ""}],
                "formats": [{"name": "Vinyl", "descriptions": ["LP", "Album"]}],
                "labels": [{"name": "Chrysalis", "catno": "CHR 1275"}],
                "country": "US",
                "year": 1980,
                "master_id": 88983,
                "community": {"have": 5000, "want": 200},
            },
            stats=mock_stats,
        )

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.release.return_value = mock_release

        results = search_marketplace(client, release_id=665695)

        assert len(results) == 1
        assert results[0].release_id == 665695
        assert results[0].artist == "Pat Benatar"
        # Should NOT have called client.master (no version scanning)
        client.master.assert_not_called()

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_release_id_populates_extended_details(self, mock_api):
        """Single release lookup should populate label, catno, format_details, community stats."""
        mock_stats = MagicMock()
        mock_stats.num_for_sale = 174
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 1.25

        mock_release = _make_mock_release(
            data={
                "id": 665695,
                "title": "Crimes Of Passion",
                "artists": [{"name": "Pat Benatar", "join": ""}],
                "formats": [{"name": "Vinyl", "descriptions": ["LP", "Album", "Reissue"]}],
                "labels": [{"name": "Chrysalis", "catno": "CHR 1275"}],
                "country": "US",
                "year": 1980,
                "master_id": 88983,
                "community": {"have": 5000, "want": 200},
            },
            stats=mock_stats,
        )

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.release.return_value = mock_release

        results = search_marketplace(client, release_id=665695, details=True)

        assert len(results) == 1
        r = results[0]
        assert r.label == "Chrysalis"
        assert r.catno == "CHR 1275"
        assert r.format_details == "LP, Album, Reissue"
        assert r.community_have == 5000
        assert r.community_want == 200

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_master_id_with_release_id_still_scans_versions(self, mock_api):
        """When both master_id and release_id are provided, master version scan should occur."""
        mock_master = MagicMock()
        mock_versions = MagicMock()
        mock_versions.page.return_value = []
        mock_master.versions = mock_versions

        mock_api.side_effect = lambda fn, *a, **kw: fn()

        client = MagicMock()
        client.master.return_value = mock_master

        results = search_marketplace(client, master_id=88983, release_id=665695)

        # Should have called client.master (version scan path)
        client.master.assert_called()


class TestSkipPriceSuggestions:
    """Price suggestions should be skipped after a seller settings 404."""

    @patch("discogs_sync.marketplace._api_call_with_retry")
    def test_skip_after_seller_settings_error(self, mock_api):
        """After seller settings 404, subsequent calls should be skipped."""
        import discogs_sync.marketplace as mp

        mock_master = MagicMock()
        v1 = MagicMock()
        v1.data = {"id": 1001, "title": "T", "format": "Vinyl", "major_formats": ["Vinyl"]}
        v2 = MagicMock()
        v2.data = {"id": 1002, "title": "T", "format": "Vinyl", "major_formats": ["Vinyl"]}

        mock_versions = MagicMock()
        mock_versions.page.side_effect = [[v1, v2], []]

        mock_stats = MagicMock()
        mock_stats.num_for_sale = 10
        mock_stats.lowest_price = MagicMock()
        mock_stats.lowest_price.value = 5.0

        call_count = [0]

        def make_release(vid):
            r = MagicMock()
            r.data = {
                "id": vid,
                "title": "Test Album",
                "artists": [{"name": "Artist", "join": ""}],
                "formats": [{"name": "Vinyl"}],
                "country": "US",
                "year": 2000,
                "master_id": 9999,
            }
            r.id = vid
            r.marketplace_stats = mock_stats

            def raise_seller_settings():
                raise Exception("404: You must fill out your seller settings first.")
            type(r).price_suggestions = property(lambda self: raise_seller_settings())
            return r

        def api_side_effect(fn, *a, **kw):
            result = fn()
            return result

        mock_api.side_effect = api_side_effect

        releases = {1001: make_release(1001), 1002: make_release(1002)}
        client = MagicMock()
        client.master.return_value = mock_master
        mock_master.versions = mock_versions
        client.release.side_effect = lambda vid: releases[vid]

        # Reset the module flag
        mp._skip_price_suggestions = False

        results = search_marketplace(client, master_id=9999, max_versions=2, details=True)

        assert len(results) == 2
        # Both should have None price_suggestions
        assert results[0].price_suggestions is None
        assert results[1].price_suggestions is None
        # The flag should be set after the first failure
        assert mp._skip_price_suggestions is True


class TestMarketplaceResultToDict:
    def test_to_dict_includes_price_suggestions(self):
        """to_dict() should include price_suggestions when not None."""
        result = MarketplaceResult(
            release_id=123,
            lowest_price=25.0,
            price_suggestions={"Near Mint (NM or M-)": 60.0, "Very Good Plus (VG+)": 40.0},
        )
        d = result.to_dict()
        assert "price_suggestions" in d
        assert d["price_suggestions"]["Near Mint (NM or M-)"] == 60.0

    def test_to_dict_omits_price_suggestions_when_none(self):
        """to_dict() should omit price_suggestions when None."""
        result = MarketplaceResult(release_id=123, lowest_price=25.0)
        d = result.to_dict()
        assert "price_suggestions" not in d

    def test_to_dict_includes_extended_fields(self):
        """to_dict() should include label, catno, format_details, community stats when set."""
        result = MarketplaceResult(
            release_id=665695,
            lowest_price=1.25,
            label="Chrysalis",
            catno="CHR 1275",
            format_details="LP, Album, Reissue",
            community_have=5000,
            community_want=200,
        )
        d = result.to_dict()
        assert d["label"] == "Chrysalis"
        assert d["catno"] == "CHR 1275"
        assert d["format_details"] == "LP, Album, Reissue"
        assert d["community_have"] == 5000
        assert d["community_want"] == 200

    def test_to_dict_omits_extended_fields_when_none(self):
        """to_dict() should omit extended fields when None."""
        result = MarketplaceResult(release_id=123, lowest_price=25.0)
        d = result.to_dict()
        assert "label" not in d
        assert "catno" not in d
        assert "format_details" not in d
        assert "community_have" not in d
        assert "community_want" not in d
