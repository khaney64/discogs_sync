"""Tests for input file parsing."""

import pytest

from discogs_sync.parsers import parse_file, parse_csv, parse_json, normalize_format
from discogs_sync.exceptions import ParseError


class TestNormalizeFormat:
    def test_vinyl_synonyms(self):
        assert normalize_format("LP") == "Vinyl"
        assert normalize_format("lp") == "Vinyl"
        assert normalize_format("record") == "Vinyl"
        assert normalize_format('12"') == "Vinyl"
        assert normalize_format("vinyl") == "Vinyl"

    def test_cd_synonyms(self):
        assert normalize_format("CD") == "CD"
        assert normalize_format("cd") == "CD"
        assert normalize_format("compact disc") == "CD"

    def test_cassette_synonyms(self):
        assert normalize_format("tape") == "Cassette"
        assert normalize_format("mc") == "Cassette"
        assert normalize_format("cassette") == "Cassette"

    def test_none_passthrough(self):
        assert normalize_format(None) is None
        assert normalize_format("") is None

    def test_unknown_format_passthrough(self):
        assert normalize_format("8-Track") == "8-Track"


class TestParseCSV:
    def test_parse_sample_csv(self, sample_csv):
        records = parse_file(sample_csv)
        assert len(records) == 5
        assert records[0].artist == "Radiohead"
        assert records[0].album == "OK Computer"
        assert records[0].format == "Vinyl"
        assert records[0].notes == "Must have"

    def test_format_normalization(self, sample_csv):
        records = parse_file(sample_csv)
        # "LP" -> "Vinyl"
        assert records[3].format == "Vinyl"
        # "record" -> "Vinyl"
        assert records[4].format == "Vinyl"

    def test_year_parsing(self, sample_csv):
        records = parse_file(sample_csv)
        assert records[1].year == 1959
        assert records[0].year is None

    def test_missing_required_artist(self, tmp_csv):
        csv_file = tmp_csv("artist,album\n,OK Computer\n")
        # 1/1 rows invalid = 100% > 50%, so it raises
        with pytest.raises(ParseError, match="Too many invalid"):
            parse_file(csv_file)

    def test_missing_required_column(self, tmp_csv):
        csv_file = tmp_csv("artist,title\nRadiohead,OK Computer\n")
        with pytest.raises(ParseError, match="missing required columns"):
            parse_file(csv_file)

    def test_empty_csv(self, tmp_csv):
        csv_file = tmp_csv("")
        with pytest.raises(ParseError):
            parse_file(csv_file)

    def test_header_only_csv(self, tmp_csv):
        csv_file = tmp_csv("artist,album\n")
        with pytest.raises(ParseError, match="no data rows"):
            parse_file(csv_file)

    def test_invalid_year(self, tmp_csv):
        csv_file = tmp_csv("artist,album,year\nRadiohead,OK Computer,abc\nNirvana,Nevermind,1991\n")
        records = parse_file(csv_file)
        # One valid, one invalid - should return the valid one
        assert len(records) == 1
        assert records[0].artist == "Nirvana"

    def test_year_out_of_range(self, tmp_csv):
        csv_file = tmp_csv("artist,album,year\nRadiohead,OK Computer,1800\nNirvana,Nevermind,1991\n")
        records = parse_file(csv_file)
        assert len(records) == 1

    def test_line_numbers(self, sample_csv):
        records = parse_file(sample_csv)
        assert records[0].line_number == 2  # line 1 is header
        assert records[1].line_number == 3

    def test_majority_invalid_aborts(self, tmp_csv):
        csv_file = tmp_csv("artist,album\n,\n,\nRadiohead,OK Computer\n")
        with pytest.raises(ParseError, match="Too many invalid"):
            parse_file(csv_file)


class TestParseJSON:
    def test_parse_sample_json(self, sample_json):
        records = parse_file(sample_json)
        assert len(records) == 5
        assert records[0].artist == "Radiohead"
        assert records[0].album == "OK Computer"
        assert records[0].format == "Vinyl"

    def test_format_normalization(self, sample_json):
        records = parse_file(sample_json)
        # "LP" -> "Vinyl"
        assert records[3].format == "Vinyl"
        # "record" -> "Vinyl"
        assert records[4].format == "Vinyl"

    def test_not_array(self, tmp_json):
        json_file = tmp_json('{"artist": "Radiohead"}')
        with pytest.raises(ParseError, match="must be an array"):
            parse_file(json_file)

    def test_empty_array(self, tmp_json):
        json_file = tmp_json("[]")
        with pytest.raises(ParseError, match="no records"):
            parse_file(json_file)

    def test_invalid_json(self, tmp_json):
        json_file = tmp_json("{bad json}")
        with pytest.raises(ParseError, match="Invalid JSON"):
            parse_file(json_file)


class TestAutoDetect:
    def test_unsupported_extension(self, tmp_path):
        p = tmp_path / "test.xml"
        p.write_text("<data/>", encoding="utf-8")
        with pytest.raises(ParseError, match="Unsupported file format"):
            parse_file(p)

    def test_file_not_found(self):
        with pytest.raises(ParseError, match="File not found"):
            parse_file("/nonexistent/file.csv")
