"""Identify a specific pressing from the matrix/runout etchings in its dead wax."""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING

from .models import RunoutMatch
from .output import print_verbose
from .parsers import extract_artist_from_data
from .rate_limiter import get_rate_limiter
from .search import _api_call_with_retry, _get_artist_name, _similarity

if TYPE_CHECKING:
    import discogs_client

MATRIX_TYPE = "Matrix / Runout"
DEFAULT_MAX_CANDIDATES = 25
ARTIST_FILTER_THRESHOLD = 0.6
MIN_BLOCK_SIZE = 2

# Hand-read etchings routinely confuse these, and Discogs submitters do too.
_LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1"})


def normalize_runout(value: str) -> str:
    """Reduce a runout to comparable characters: uppercase alphanumerics, lookalikes folded."""
    return re.sub(r"[^A-Z0-9]", "", value.upper().translate(_LOOKALIKES))


def runout_score(given: str, candidate: str) -> float:
    """Fraction of the given runout found, in order, within a candidate runout (0.0-1.0)."""
    g = normalize_runout(given)
    c = normalize_runout(candidate)
    if not g or not c:
        return 0.0
    if g in c:
        return 1.0
    matcher = difflib.SequenceMatcher(None, g, c, autojunk=False)
    matched = sum(b.size for b in matcher.get_matching_blocks() if b.size >= MIN_BLOCK_SIZE)
    return matched / len(g)


def identify_release(
    client: discogs_client.Client,
    runouts: list[str],
    artist: str | None = None,
    album: str | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    verbose: bool = False,
) -> list[RunoutMatch]:
    """Find releases whose Matrix / Runout identifiers best match the given etchings.

    Candidates come from the database search's barcode parameter (which also
    indexes matrix/runout identifiers), narrowed by artist/album when given. Each
    candidate's full release is fetched and scored locally, best first.
    """
    limiter = get_rate_limiter()
    candidate_ids = _find_candidates(client, runouts, artist, album, max_candidates, limiter, verbose)

    matches = []
    for release_id in candidate_ids:
        release = _api_call_with_retry(lambda r=release_id: client.release(r), limiter, verbose=verbose, description=f"release({release_id})")
        _api_call_with_retry(lambda: release.refresh(), limiter, verbose=verbose, description=f"release({release_id}).refresh()")
        matches.append(_score_release(release_id, release.data, runouts))

    matches.sort(key=lambda m: (m.score, m.community_have or 0), reverse=True)
    return matches


def _find_candidates(client, runouts, artist, album, max_candidates, limiter, verbose) -> list[int]:
    """Pool every runout search, narrowest first; fall back to the album's vinyl releases if none hit.

    Runout searches are pooled rather than stopping at the first hit, because a
    narrow search can return only near-misses (e.g. club editions whose active
    matrix is the runout given) and hide the pressings where it is crossed out.
    """
    runout_queries, fallback_queries = _candidate_queries(runouts, artist, album)
    ids = _search_ids(client, runout_queries, artist, limiter, verbose)
    if not ids:
        ids = _search_ids(client, fallback_queries, artist, limiter, verbose)
    if verbose:
        print_verbose(f"Found {len(ids)} candidate release(s); checking up to {max_candidates}")
    return ids[:max_candidates]


def _search_ids(client, queries: list[dict], artist: str | None, limiter, verbose) -> list[int]:
    ids: list[int] = []
    for query in queries:
        if verbose:
            print_verbose(f"Searching releases: {query}")
        results = _api_call_with_retry(lambda q=query: client.search(type="release", **q), limiter)
        try:
            page = _api_call_with_retry(lambda: results.page(1), limiter)
        except Exception:
            continue
        for item in page:
            if artist and _similarity(artist, _get_artist_name(item)) < ARTIST_FILTER_THRESHOLD:
                continue
            if item.id not in ids:
                ids.append(item.id)
    return ids


def _candidate_queries(runouts: list[str], artist: str | None, album: str | None) -> tuple[list[dict], list[dict]]:
    """Return (runout queries, narrowest first; fallback queries used only when those find nothing)."""
    filter_sets = [{"artist": artist, "release_title": album}, {"artist": artist}, {}]
    runout_queries: list[dict] = []
    for filters in filter_sets:
        filters = {k: v for k, v in filters.items() if v}
        for r in runouts:
            query = {**filters, "barcode": r}
            if query not in runout_queries:
                runout_queries.append(query)

    # Runout not indexed or misread: score every vinyl release of the album instead.
    fallback_queries = [{"artist": artist, "release_title": album, "format": "Vinyl"}] if artist and album else []
    return runout_queries, fallback_queries


def _score_release(release_id: int, data: dict, runouts: list[str]) -> RunoutMatch:
    etchings = [
        i.get("value", "") for i in data.get("identifiers", [])
        if isinstance(i, dict) and i.get("type") == MATRIX_TYPE
    ]

    matched = []
    for given in runouts:
        best_score, best_etching = 0.0, None
        for etching in etchings:
            score = runout_score(given, etching)
            if score > best_score:
                best_score, best_etching = score, etching
        matched.append({"input": given, "runout": best_etching, "score": round(best_score, 3)})

    labels = data.get("labels") or [{}]
    community = data.get("community") or {}
    return RunoutMatch(
        release_id=release_id,
        score=sum(m["score"] for m in matched) / len(matched) if matched else 0.0,
        master_id=data.get("master_id"),
        title=data.get("title"),
        artist=extract_artist_from_data(data),
        year=data.get("year"),
        country=data.get("country"),
        label=labels[0].get("name"),
        catno=labels[0].get("catno"),
        format_details=_describe_formats(data.get("formats", [])),
        community_have=community.get("have"),
        matched_runouts=matched,
        runouts=etchings,
    )


def _describe_formats(formats: list) -> str | None:
    """e.g. 'Vinyl LP, Album, Reissue (Crystal Clear / Black Mix, 180g)'."""
    parts = []
    for f in formats:
        if not isinstance(f, dict):
            continue
        text = " ".join(filter(None, [f.get("name"), ", ".join(f.get("descriptions", []))]))
        if f.get("text"):
            text += f" ({f['text']})"
        parts.append(text)
    return "; ".join(parts) or None
