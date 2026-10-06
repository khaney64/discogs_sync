"""Tests for runout-based release identification."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from discogs_sync.cli import main
from discogs_sync.identify import (
    _candidate_query_tiers,
    _describe_formats,
    identify_release,
    normalize_runout,
    runout_score,
)


def _search_hit(release_id, title):
    hit = MagicMock()
    hit.id = release_id
    hit.data = {"title": title}
    hit.title = title
    return hit


def _release_data(release_id, runouts, have=0, title="The Dreaming", artist="Kate Bush"):
    return {
        "id": release_id,
        "title": title,
        "artists": [{"name": artist}],
        "master_id": 28613,
        "year": 2024,
        "country": "Worldwide",
        "labels": [{"name": "Fish People", "catno": f"CAT{release_id}"}],
        "formats": [{"name": "Vinyl", "descriptions": ["LP", "Album"], "text": "180g"}],
        "community": {"have": have},
        "identifiers": [{"type": "Matrix / Runout", "value": v} for v in runouts]
        + [{"type": "Barcode", "value": "5057998501809"}],
    }


def _client(search_pages, releases):
    """search_pages: list of hit lists returned by successive client.search() calls."""
    client = MagicMock()
    results = []
    for hits in search_pages:
        r = MagicMock()
        r.page.return_value = hits
        results.append(r)
    client.search.side_effect = results

    def make_release(release_id):
        release = MagicMock()
        release.data = releases[release_id]
        return release

    client.release.side_effect = make_release
    return client


@pytest.fixture(autouse=True)
def _no_throttle():
    with patch("discogs_sync.search.get_rate_limiter"), patch("discogs_sync.identify.get_rate_limiter"):
        yield


class TestNormalizeRunout:
    def test_strips_spacing_and_punctuation(self):
        assert normalize_runout("FP 04LP - A") == normalize_runout("FP04LP-A")

    def test_folds_letter_o_to_zero(self):
        assert normalize_runout("FPO4LP-A") == normalize_runout("FP 04LP - A")

    def test_folds_i_and_l_to_one(self):
        assert normalize_runout("ST-I") == normalize_runout("st-1") == normalize_runout("ST-L")

    def test_drops_symbols(self):
        assert normalize_runout("FPO4LP-A 401241 1A BG ▽") == normalize_runout("FPO4LP-A 401241 1A BG")


class TestRunoutScore:
    def test_partial_runout_contained_scores_full(self):
        assert runout_score("FP 04LP - A", "FPO4LP-A 401241 1A BG") == 1.0

    def test_wrong_side_scores_below_full(self):
        assert runout_score("FP 04LP - A", "FPO4LP-B 401241 3") < 1.0

    def test_unrelated_runout_scores_low(self):
        assert runout_score("FP 04LP - A", "ST-1-17084-P-3 Mastered By Liberty") < 0.5

    def test_empty_inputs_score_zero(self):
        assert runout_score("", "FPO4LP-A") == 0.0
        assert runout_score("FPO4LP-A", "—◁") == 0.0


class TestCandidateQueryTiers:
    def test_artist_and_album_tiers_broaden(self):
        tiers = _candidate_query_tiers(["A1"], "Kate Bush", "The Dreaming")
        assert tiers[0] == [{"artist": "Kate Bush", "release_title": "The Dreaming", "barcode": "A1"}]
        assert tiers[1] == [{"artist": "Kate Bush", "barcode": "A1"}]
        assert tiers[2] == [{"artist": "Kate Bush", "release_title": "The Dreaming", "format": "Vinyl"}]

    def test_runout_only_is_single_tier(self):
        assert _candidate_query_tiers(["A1", "B1"], None, None) == [[{"barcode": "A1"}, {"barcode": "B1"}]]


class TestIdentifyRelease:
    def test_ranks_full_match_first(self):
        client = _client(
            [[_search_hit(1, "Kate Bush - The Dreaming"), _search_hit(2, "Kate Bush - The Dreaming")]],
            {
                1: _release_data(1, ["ST-1-17084", "ST-2-17084"]),
                2: _release_data(2, ["FPO4LP-A 401241 1A BG", "FPO4LP-B 401241 3"]),
            },
        )

        matches = identify_release(client, ["FP 04LP - A"], artist="Kate Bush")

        assert [m.release_id for m in matches] == [2, 1]
        assert matches[0].score == 1.0
        assert matches[0].matched_runouts[0]["runout"] == "FPO4LP-A 401241 1A BG"
        assert matches[0].runouts == ["FPO4LP-A 401241 1A BG", "FPO4LP-B 401241 3"]

    def test_score_averages_sides_and_ties_break_on_have(self):
        client = _client(
            [[_search_hit(1, "Kate Bush - The Dreaming"), _search_hit(2, "Kate Bush - The Dreaming")],
             [_search_hit(2, "Kate Bush - The Dreaming")]],
            {
                1: _release_data(1, ["FPO4LP-A", "FPO4LP-B"], have=10),
                2: _release_data(2, ["FPO4LP-A", "FPO4LP-B"], have=500),
            },
        )

        matches = identify_release(client, ["FP04LP-A", "FP04LP-B"], artist="Kate Bush")

        assert [m.release_id for m in matches] == [2, 1]
        assert client.release.call_count == 2

    def test_filters_other_artists_from_search_hits(self):
        client = _client(
            [[_search_hit(1, "Phish - Livephish"), _search_hit(2, "Kate Bush - The Dreaming")]],
            {2: _release_data(2, ["FPO4LP-A"])},
        )

        matches = identify_release(client, ["FP 04LP - A"], artist="Kate Bush")

        assert [m.release_id for m in matches] == [2]

    def test_falls_back_to_broader_tier_when_first_is_empty(self):
        client = _client(
            [[], [_search_hit(2, "Kate Bush - The Dreaming")]],
            {2: _release_data(2, ["FPO4LP-A"])},
        )

        matches = identify_release(client, ["FP 04LP - A"], artist="Kate Bush", album="The Dreaming")

        assert [m.release_id for m in matches] == [2]
        assert "release_title" not in client.search.call_args_list[1].kwargs

    def test_respects_max_candidates(self):
        hits = [_search_hit(i, "Kate Bush - The Dreaming") for i in range(1, 6)]
        client = _client([hits], {i: _release_data(i, ["X"]) for i in range(1, 6)})

        identify_release(client, ["X"], artist="Kate Bush", max_candidates=2)

        assert client.release.call_count == 2

    def test_no_candidates_returns_empty(self):
        client = _client([[]], {})

        assert identify_release(client, ["NOPE"]) == []


class TestDescribeFormats:
    def test_includes_descriptions_and_text(self):
        formats = [{"name": "Vinyl", "descriptions": ["LP", "Album"], "text": "Crystal Clear"}]
        assert _describe_formats(formats) == "Vinyl LP, Album (Crystal Clear)"

    def test_empty(self):
        assert _describe_formats([]) is None


class TestReleaseIdentifyCli:
    @patch("discogs_sync.identify.identify_release")
    @patch("discogs_sync.client_factory.build_client")
    def test_json_output_respects_limit(self, _mock_client, mock_identify):
        from discogs_sync.models import RunoutMatch
        mock_identify.return_value = [RunoutMatch(release_id=i, score=1.0) for i in range(1, 8)]

        result = CliRunner().invoke(main, [
            "release", "identify", "--runout", "FP 04LP - A", "--runout", "FP 04LP - B",
            "--artist", "Kate Bush", "--limit", "3", "--output-format", "json",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 3
        assert mock_identify.call_args.args[1] == ["FP 04LP - A", "FP 04LP - B"]

    @patch("discogs_sync.identify.identify_release")
    @patch("discogs_sync.client_factory.build_client")
    def test_table_output(self, _mock_client, mock_identify):
        from discogs_sync.models import RunoutMatch
        mock_identify.return_value = [RunoutMatch(
            release_id=29576638, score=1.0, artist="Kate Bush", title="The Dreaming",
            label="Fish People", catno="FP4LPSE",
            matched_runouts=[{"input": "FP 04LP - A", "runout": "FPO4LP-A", "score": 1.0}],
        )]

        result = CliRunner().invoke(main, ["release", "identify", "--runout", "FP 04LP - A"])

        assert result.exit_code == 0
        assert "29576638" in result.output
        assert "Total: 1" in result.output

    def test_runout_required(self):
        result = CliRunner().invoke(main, ["release", "identify", "--artist", "Kate Bush"])
        assert result.exit_code == 2
