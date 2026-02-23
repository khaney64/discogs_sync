"""Marketplace stats lookup via master versions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .exceptions import SyncError
from .models import InputRecord, MarketplaceResult
from .rate_limiter import get_rate_limiter
from .search import (
    _api_call_with_retry,
    resolve_to_release_id,
    search_release,
)

if TYPE_CHECKING:
    import discogs_client

DEFAULT_MAX_VERSIONS = 25


def search_marketplace(
    client: discogs_client.Client,
    master_id: int | None = None,
    release_id: int | None = None,
    artist: str | None = None,
    album: str | None = None,
    format: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    currency: str = "USD",
    max_versions: int = DEFAULT_MAX_VERSIONS,
    threshold: float = 0.7,
) -> list[MarketplaceResult]:
    """Search marketplace stats for a single item.

    Resolves to master_id, fetches versions, gets stats for each.
    """
    limiter = get_rate_limiter()

    # Resolve to master_id
    if not master_id:
        if release_id:
            # Get master from release
            release = _api_call_with_retry(lambda: client.release(release_id), limiter)
            data = release.data if hasattr(release, "data") else {}
            master_id = data.get("master_id")
            if not master_id:
                # No master - just get stats for this release
                return _get_stats_for_release(client, release_id, currency, min_price, max_price, limiter)
        elif artist and album:
            record = InputRecord(artist=artist, album=album, format=format)
            result = search_release(client, record, threshold=threshold)
            if not result.matched:
                raise SyncError(f"No match found for {artist} - {album}")
            master_id = result.master_id
            if not master_id and result.release_id:
                release = _api_call_with_retry(lambda: client.release(result.release_id), limiter)
                data = release.data if hasattr(release, "data") else {}
                master_id = data.get("master_id")
            if not master_id:
                # Fall back to single release stats
                rid = resolve_to_release_id(client, result)
                if rid:
                    return _get_stats_for_release(client, rid, currency, min_price, max_price, limiter)
                raise SyncError(f"Could not resolve master or release for {artist} - {album}")
        else:
            raise SyncError("Must provide --master-id, --release-id, or both --artist and --album")

    # Fetch master versions
    master = _api_call_with_retry(lambda: client.master(master_id), limiter)
    versions = _api_call_with_retry(lambda: master.versions, limiter)

    results: list[MarketplaceResult] = []
    count = 0
    page_num = 1

    while count < max_versions:
        try:
            page = _api_call_with_retry(lambda p=page_num: versions.page(p), limiter)
            if not page:
                break
        except Exception:
            break

        for version in page:
            if count >= max_versions:
                break

            data = version.data if hasattr(version, "data") else {}
            version_id = data.get("id") or getattr(version, "id", None)
            if not version_id:
                continue

            # Filter by format if specified
            if format:
                version_formats = data.get("major_formats", [])
                if not version_formats:
                    fmt_str = data.get("format", "")
                    version_formats = [fmt_str] if fmt_str else []
                if not any(format.lower() in str(f).lower() for f in version_formats):
                    continue

            # Get marketplace stats
            try:
                release = _api_call_with_retry(lambda vid=version_id: client.release(vid), limiter)
                release_data = release.data if hasattr(release, "data") else {}
                stats = _api_call_with_retry(lambda r=release: r.marketplace_stats, limiter)

                num_for_sale = 0
                lowest_price = None

                if hasattr(stats, "num_for_sale"):
                    num_for_sale = stats.num_for_sale or 0
                elif isinstance(stats, dict):
                    num_for_sale = stats.get("num_for_sale", 0)

                if hasattr(stats, "lowest_price"):
                    lp = stats.lowest_price
                    if lp is not None:
                        if hasattr(lp, "value"):
                            lowest_price = float(lp.value)
                        elif isinstance(lp, dict):
                            lowest_price = float(lp.get("value", 0))
                        else:
                            lowest_price = float(lp)
                elif isinstance(stats, dict):
                    lp = stats.get("lowest_price")
                    if lp is not None:
                        if isinstance(lp, dict):
                            lowest_price = float(lp.get("value", 0))
                        else:
                            lowest_price = float(lp)

                # Apply price filters
                if min_price is not None and (lowest_price is None or lowest_price < min_price):
                    continue
                if max_price is not None and (lowest_price is None or lowest_price > max_price):
                    continue

                # Parse title
                title = release_data.get("title", data.get("title", ""))
                artist_name = ""
                album_name = title
                if " - " in title:
                    artist_name, album_name = title.split(" - ", 1)

                # Parse format
                fmt = None
                formats = release_data.get("formats", [])
                if formats and isinstance(formats, list):
                    fmt = formats[0].get("name", "") if isinstance(formats[0], dict) else str(formats[0])
                if not fmt:
                    fmt = data.get("format", "")

                results.append(MarketplaceResult(
                    master_id=master_id,
                    release_id=version_id,
                    title=album_name,
                    artist=artist_name,
                    format=fmt,
                    country=release_data.get("country", data.get("country")),
                    year=release_data.get("year", data.get("year")),
                    num_for_sale=num_for_sale,
                    lowest_price=lowest_price,
                    currency=currency,
                ))

                count += 1

            except Exception:
                continue

        page_num += 1

    # Sort by lowest_price ascending (None values at end)
    results.sort(key=lambda r: (r.lowest_price is None, r.lowest_price or 0))

    return results


def search_marketplace_batch(
    client: discogs_client.Client,
    records: list[InputRecord],
    format: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    currency: str = "USD",
    max_versions: int = DEFAULT_MAX_VERSIONS,
    threshold: float = 0.7,
) -> tuple[list[MarketplaceResult], list[dict]]:
    """Search marketplace for a batch of records.

    Returns (results, errors) where errors is a list of error dicts.
    """
    all_results: list[MarketplaceResult] = []
    errors: list[dict] = []

    for record in records:
        try:
            results = search_marketplace(
                client,
                artist=record.artist,
                album=record.album,
                format=format or record.format,
                min_price=min_price,
                max_price=max_price,
                currency=currency,
                max_versions=max_versions,
                threshold=threshold,
            )
            all_results.extend(results)
        except Exception as e:
            errors.append({
                "artist": record.artist,
                "album": record.album,
                "error": str(e),
            })

    return all_results, errors


def _get_stats_for_release(
    client,
    release_id: int,
    currency: str,
    min_price: float | None,
    max_price: float | None,
    limiter,
) -> list[MarketplaceResult]:
    """Get marketplace stats for a single release."""
    release = _api_call_with_retry(lambda: client.release(release_id), limiter)
    data = release.data if hasattr(release, "data") else {}
    stats = _api_call_with_retry(lambda: release.marketplace_stats, limiter)

    num_for_sale = 0
    lowest_price = None

    if hasattr(stats, "num_for_sale"):
        num_for_sale = stats.num_for_sale or 0
    elif isinstance(stats, dict):
        num_for_sale = stats.get("num_for_sale", 0)

    if hasattr(stats, "lowest_price"):
        lp = stats.lowest_price
        if lp is not None:
            if hasattr(lp, "value"):
                lowest_price = float(lp.value)
            elif isinstance(lp, dict):
                lowest_price = float(lp.get("value", 0))
            else:
                lowest_price = float(lp)
    elif isinstance(stats, dict):
        lp = stats.get("lowest_price")
        if lp is not None:
            if isinstance(lp, dict):
                lowest_price = float(lp.get("value", 0))
            else:
                lowest_price = float(lp)

    if min_price is not None and (lowest_price is None or lowest_price < min_price):
        return []
    if max_price is not None and (lowest_price is None or lowest_price > max_price):
        return []

    title = data.get("title", "")
    artist_name = ""
    album_name = title
    if " - " in title:
        artist_name, album_name = title.split(" - ", 1)

    fmt = None
    formats = data.get("formats", [])
    if formats and isinstance(formats, list):
        fmt = formats[0].get("name", "") if isinstance(formats[0], dict) else str(formats[0])

    return [MarketplaceResult(
        master_id=data.get("master_id"),
        release_id=release_id,
        title=album_name,
        artist=artist_name,
        format=fmt,
        country=data.get("country"),
        year=data.get("year"),
        num_for_sale=num_for_sale,
        lowest_price=lowest_price,
        currency=currency,
    )]
