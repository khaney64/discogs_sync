"""Wantlist sync operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .exceptions import NetworkError, SyncError
from .models import (
    InputRecord,
    SearchResult,
    SyncAction,
    SyncActionType,
    SyncReport,
    WantlistItem,
)
from .output import print_info, print_warning
from .rate_limiter import get_rate_limiter
from .search import (
    _api_call_with_retry,
    resolve_master_id,
    resolve_to_release_id,
    search_release,
)

if TYPE_CHECKING:
    import discogs_client


def sync_wantlist(
    client: discogs_client.Client,
    records: list[InputRecord],
    remove_extras: bool = False,
    dry_run: bool = False,
    threshold: float = 0.7,
) -> SyncReport:
    """Sync a list of input records to the user's wantlist.

    1. Resolve each record to a release_id
    2. Fetch current wantlist
    3. Diff and apply changes
    """
    report = SyncReport(total_input=len(records))
    limiter = get_rate_limiter()

    # Step 1: Resolve all records
    resolved: list[tuple[InputRecord, SearchResult]] = []
    for record in records:
        try:
            result = search_release(client, record, threshold=threshold)
            if result.matched:
                release_id = resolve_to_release_id(client, result)
                if release_id:
                    result.release_id = release_id
                    resolved.append((record, result))
                else:
                    report.add_action(SyncAction(
                        action=SyncActionType.ERROR,
                        input_record=record,
                        error="Could not resolve to release ID",
                    ))
            else:
                report.add_action(SyncAction(
                    action=SyncActionType.ERROR,
                    input_record=record,
                    error=result.error or "No match found",
                ))
        except Exception as e:
            report.add_action(SyncAction(
                action=SyncActionType.ERROR,
                input_record=record,
                error=str(e),
            ))

    # Step 2: Fetch current wantlist
    current_ids = _get_wantlist_release_ids(client, limiter)

    # Step 3: Diff
    target_ids = set()
    for record, result in resolved:
        release_id = result.release_id
        target_ids.add(release_id)

        if release_id in current_ids:
            report.add_action(SyncAction(
                action=SyncActionType.SKIP,
                input_record=record,
                release_id=release_id,
                master_id=result.master_id,
                title=result.title,
                artist=result.artist,
                reason="Already in wantlist",
            ))
        else:
            if not dry_run:
                try:
                    _add_to_wantlist(client, release_id, limiter)
                except Exception as e:
                    report.add_action(SyncAction(
                        action=SyncActionType.ERROR,
                        input_record=record,
                        release_id=release_id,
                        error=f"Failed to add: {e}",
                    ))
                    continue

            report.add_action(SyncAction(
                action=SyncActionType.ADD,
                input_record=record,
                release_id=release_id,
                master_id=result.master_id,
                title=result.title,
                artist=result.artist,
                reason="Dry run" if dry_run else None,
            ))

    # Step 4: Remove extras if requested
    if remove_extras:
        extras = current_ids - target_ids
        for release_id in extras:
            if not dry_run:
                try:
                    _remove_from_wantlist(client, release_id, limiter)
                except Exception as e:
                    report.add_action(SyncAction(
                        action=SyncActionType.ERROR,
                        release_id=release_id,
                        error=f"Failed to remove: {e}",
                    ))
                    continue

            report.add_action(SyncAction(
                action=SyncActionType.REMOVE,
                release_id=release_id,
                reason="Not in input file" + (" (dry run)" if dry_run else ""),
            ))

    return report


def add_to_wantlist(
    client: discogs_client.Client,
    release_id: int | None = None,
    master_id: int | None = None,
    artist: str | None = None,
    album: str | None = None,
    format: str | None = None,
    threshold: float = 0.7,
) -> SyncAction:
    """Add a single item to the wantlist."""
    limiter = get_rate_limiter()

    # Resolve release_id
    release_id = _resolve_item(
        client, release_id=release_id, master_id=master_id,
        artist=artist, album=album, format=format, threshold=threshold,
    )

    # Check for duplicates
    current_ids = _get_wantlist_release_ids(client, limiter)
    if release_id in current_ids:
        return SyncAction(
            action=SyncActionType.SKIP,
            release_id=release_id,
            artist=artist,
            title=album,
            reason="Already in wantlist",
        )

    _add_to_wantlist(client, release_id, limiter)

    return SyncAction(
        action=SyncActionType.ADD,
        release_id=release_id,
        artist=artist,
        title=album,
    )


def remove_from_wantlist(
    client: discogs_client.Client,
    release_id: int | None = None,
    artist: str | None = None,
    album: str | None = None,
    format: str | None = None,
    threshold: float = 0.7,
) -> SyncAction:
    """Remove a single item from the wantlist."""
    limiter = get_rate_limiter()

    release_id = _resolve_item(
        client, release_id=release_id, artist=artist, album=album,
        format=format, threshold=threshold,
    )

    # Check if it's actually in the wantlist
    current_ids = _get_wantlist_release_ids(client, limiter)
    if release_id not in current_ids:
        return SyncAction(
            action=SyncActionType.SKIP,
            release_id=release_id,
            artist=artist,
            title=album,
            reason="Not in wantlist",
        )

    _remove_from_wantlist(client, release_id, limiter)

    return SyncAction(
        action=SyncActionType.REMOVE,
        release_id=release_id,
        artist=artist,
        title=album,
    )


def list_wantlist(client: discogs_client.Client) -> list[WantlistItem]:
    """Fetch and return all wantlist items."""
    limiter = get_rate_limiter()
    me = _api_call_with_retry(lambda: client.identity(), limiter)
    wantlist = _api_call_with_retry(lambda: me.wantlist, limiter)

    items = []
    page_num = 1
    while True:
        try:
            page = _api_call_with_retry(lambda p=page_num: wantlist.page(p), limiter)
            if not page:
                break
            for item in page:
                release = item.release if hasattr(item, "release") else item
                data = release.data if hasattr(release, "data") else {}

                # Parse artist from title
                title = data.get("title", "")
                artist_name = ""
                album_name = title
                if " - " in title:
                    artist_name, album_name = title.split(" - ", 1)

                fmt = None
                formats = data.get("formats", [])
                if formats and isinstance(formats, list):
                    fmt = formats[0].get("name", "") if isinstance(formats[0], dict) else str(formats[0])

                items.append(WantlistItem(
                    release_id=data.get("id", getattr(release, "id", 0)),
                    master_id=data.get("master_id"),
                    title=album_name,
                    artist=artist_name,
                    format=fmt,
                    year=data.get("year"),
                    notes=getattr(item, "notes", None),
                ))
            page_num += 1
        except Exception:
            break

    return items


def _resolve_item(
    client,
    release_id: int | None = None,
    master_id: int | None = None,
    artist: str | None = None,
    album: str | None = None,
    format: str | None = None,
    threshold: float = 0.7,
) -> int:
    """Resolve various input forms to a release_id."""
    if release_id:
        return release_id

    if master_id:
        return resolve_master_id(client, master_id, preferred_format=format)

    if not artist or not album:
        raise SyncError("Must provide --release-id, --master-id, or both --artist and --album")

    record = InputRecord(artist=artist, album=album, format=format)
    result = search_release(client, record, threshold=threshold)
    if not result.matched:
        raise SyncError(f"No match found for {record.display_name()}")

    resolved_id = resolve_to_release_id(client, result)
    if not resolved_id:
        raise SyncError(f"Could not resolve release ID for {record.display_name()}")

    return resolved_id


def _get_wantlist_release_ids(client, limiter) -> set[int]:
    """Fetch all release IDs currently in the wantlist."""
    me = _api_call_with_retry(lambda: client.identity(), limiter)
    wantlist = _api_call_with_retry(lambda: me.wantlist, limiter)

    ids = set()
    page_num = 1
    while True:
        try:
            page = _api_call_with_retry(lambda p=page_num: wantlist.page(p), limiter)
            if not page:
                break
            for item in page:
                release = item.release if hasattr(item, "release") else item
                data = release.data if hasattr(release, "data") else {}
                rid = data.get("id") or getattr(release, "id", None)
                if rid:
                    ids.add(rid)
            page_num += 1
        except Exception:
            break

    return ids


def _add_to_wantlist(client, release_id: int, limiter) -> None:
    """Add a release to the wantlist via API."""
    me = _api_call_with_retry(lambda: client.identity(), limiter)
    _api_call_with_retry(lambda: me.wantlist.add(release_id), limiter)


def _remove_from_wantlist(client, release_id: int, limiter) -> None:
    """Remove a release from the wantlist via API."""
    me = _api_call_with_retry(lambda: client.identity(), limiter)
    _api_call_with_retry(lambda: me.wantlist.remove(release_id), limiter)
