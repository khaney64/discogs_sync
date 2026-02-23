"""Tests for release search and matching."""

from unittest.mock import MagicMock, patch

import pytest

from discogs_sync.models import InputRecord
from discogs_sync.search import _compute_score, _similarity, search_release


class TestSimilarity:
    def test_exact_match(self):
        assert _similarity("Radiohead", "Radiohead") == 1.0

    def test_case_insensitive(self):
        assert _similarity("radiohead", "Radiohead") == 1.0

    def test_partial_match(self):
        score = _similarity("Radio", "Radiohead")
        assert 0.5 < score < 1.0

    def test_empty_strings(self):
        assert _similarity("", "Radiohead") == 0.0
        assert _similarity("Radiohead", "") == 0.0
        assert _similarity("", "") == 0.0

    def test_completely_different(self):
        score = _similarity("Radiohead", "Miles Davis")
        assert score < 0.5


class TestComputeScore:
    def _make_result(self, title="Radiohead - OK Computer", year=None, formats=None):
        result = MagicMock()
        result.title = title
        result.data = {"title": title}
        if year:
            result.data["year"] = year
        if formats:
            result.data["format"] = formats
        return result

    def test_perfect_match(self):
        record = InputRecord(artist="Radiohead", album="OK Computer")
        result = self._make_result()
        score = _compute_score(result, record)
        assert score > 0.7

    def test_artist_album_weight(self):
        record = InputRecord(artist="Radiohead", album="OK Computer")
        result = self._make_result("Radiohead - OK Computer")
        score = _compute_score(result, record)
        # Artist (40%) + album (40%) both exact = 0.8
        assert score >= 0.75

    def test_year_bonus(self):
        record = InputRecord(artist="Radiohead", album="OK Computer", year=1997)
        result_with_year = self._make_result(year=1997)
        result_without_year = self._make_result()
        score_with = _compute_score(result_with_year, record)
        score_without = _compute_score(result_without_year, record)
        assert score_with > score_without

    def test_format_bonus(self):
        record = InputRecord(artist="Radiohead", album="OK Computer", format="Vinyl")
        result_with_fmt = self._make_result(formats=["Vinyl"])
        result_without_fmt = self._make_result()
        score_with = _compute_score(result_with_fmt, record)
        score_without = _compute_score(result_without_fmt, record)
        assert score_with > score_without

    def test_wrong_artist(self):
        record = InputRecord(artist="Radiohead", album="OK Computer")
        result = self._make_result("Miles Davis - Kind of Blue")
        score = _compute_score(result, record)
        assert score < 0.3


class TestSearchRelease:
    @patch("discogs_sync.search._api_call_with_retry")
    def test_no_results(self, mock_api):
        """When API returns no results, search returns unmatched."""
        mock_api.return_value = None
        client = MagicMock()
        record = InputRecord(artist="Unknown Artist", album="Unknown Album")
        result = search_release(client, record, threshold=0.7)
        assert not result.matched

    @patch("discogs_sync.search._api_call_with_retry")
    def test_structured_match(self, mock_api):
        """When structured search finds a good match."""
        mock_result = MagicMock()
        mock_result.title = "Radiohead - OK Computer"
        mock_result.data = {
            "title": "Radiohead - OK Computer",
            "type": "master",
            "id": 3425,
            "year": 1997,
        }

        mock_page = [mock_result]
        mock_results = MagicMock()
        mock_results.page.return_value = mock_page

        # First call returns results, subsequent calls for other passes
        mock_api.return_value = mock_results

        client = MagicMock()
        record = InputRecord(artist="Radiohead", album="OK Computer")
        result = search_release(client, record, threshold=0.7)
        assert result.matched
        assert result.master_id == 3425
