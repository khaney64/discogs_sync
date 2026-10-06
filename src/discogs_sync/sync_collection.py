"""Collection sync operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from discogs_client.models import CollectionItemInstance

from .exceptions import ConfirmationRequiredError, SyncError
from .models import (
    CollectionItem,
    InputRecord,
    SearchResult,
    SyncAction,
    SyncActionType,
    SyncReport,
)
from .output import print_info, print_verbose
from .parsers import extract_artist_from_data
from .rate_limiter import get_rate_limiter
from .search import (
    _api_call_with_retry,
    _similarity,
    resolve_master_id,
    resolve_to_release_id,
    search_release,
)
from .sync_wantlist import check_remove_extras_allowed, describe_release

if TYPE_CHECKING:
    import discogs_client

DEFAULT_ADD_FOLDER = 1   # "Uncategorized"
DEFAULT_READ_FOLDER = 0  # "All"
FUZZY_MATCH_THRESHOLD = 0.85


def sync_collection(
    client: discogs_client.Client,
    records: list[InputRecord],
    folder_id: int = DEFAULT_ADD_FOLDER,
    remove_extras: bool = False,
    dry_run: bool = False,
    threshold: float = 0.7,
    verbose: bool = False,
    confirm_removals: bool = False,
) -> SyncReport:
    """Sync a list of input records to the user's collection.

    With remove_extras (and not dry_run), raises SyncError before any change is
    made if an input record failed to resolve or if confirm_removals is False.
    """
    report = SyncReport(total_input=len(records))
    limiter = get_rate_limiter()

    if verbose:
        print_verbose(f"Starting collection sync: {len(records)} input records, folder_id={folder_id}, threshold={threshold}, dry_run={dry_run}, remove_extras={remove_extras}")

    # Step 1: Resolve all records
    resolved: list[tuple[InputRecord, SearchResult]] = []
    for i, record in enumerate(records, 1):
        if verbose:
            print_verbose(f"[{i}/{len(records)}] Searching: {record.artist} - {record.album}" + (f" [{record.format}]" if record.format else ""))
        try:
            result = search_release(client, record, threshold=threshold)
            if result.matched:
                if verbose:
                    print_verbose(f"  Matched: {result.artist} - {result.title} (score={result.score:.2f}, master_id={result.master_id}, release_id={result.release_id})")
                release_id = resolve_to_release_id(client, result)
                if release_id:
                    if verbose and release_id != result.release_id:
                        print_verbose(f"  Resolved to release_id={release_id}")
                    result.release_id = release_id
                    resolved.append((record, result))
                else:
                    if verbose:
                        print_verbose(f"  Failed to resolve to release ID")
                    report.add_action(SyncAction(
                        action=SyncActionType.ERROR,
                        input_record=record,
                        error="Could not resolve to release ID",
                    ))
            else:
                if verbose:
                    print_verbose(f"  No match: {result.error or 'below threshold'}")
                report.add_action(SyncAction(
                    action=SyncActionType.ERROR,
                    input_record=record,
                    error=result.error or "No match found",
                ))
        except Exception as e:
            if verbose:
                print_verbose(f"  Error: {e}")
            report.add_action(SyncAction(
                action=SyncActionType.ERROR,
                input_record=record,
                error=str(e),
            ))

    if verbose:
        print_verbose(f"Resolved {len(resolved)}/{len(records)} records")

    # Step 2: Fetch current collection
    if verbose:
        print_verbose("Fetching current collection...")
    current, current_masters, current_items = _get_collection_release_ids(client, DEFAULT_READ_FOLDER, limiter)
    if verbose:
        print_verbose(f"Current collection has {len(current)} unique releases, {len(current_masters)} unique masters")

    # Plan preservation before confirmation or writes. Keep the actual pressings
    # that satisfy an input, not just the release IDs returned by search.
    target_ids = {result.release_id for _, result in resolved}
    matches = []
    for _, result in resolved:
        if result.release_id in current:
            matching_ids = {result.release_id}
        elif result.master_id and result.master_id in current_masters:
            matching_ids = current_masters[result.master_id]
        else:
            matching_ids = _fuzzy_match_release_ids(result.artist, result.title, current_items, verbose)
        matches.append(matching_ids)
        target_ids.update(matching_ids)
    extras = set(current) - target_ids

    if remove_extras and not dry_run:
        pending = sum(len(current[release_id]) for release_id in extras)
        check_remove_extras_allowed(report, pending, confirm_removals)

    # Step 3: Diff
    for (record, result), matching_ids in zip(resolved, matches):
        release_id = result.release_id

        if release_id in current:
            if verbose:
                print_verbose(f"  SKIP (release_id match): {result.artist} - {result.title} (release_id={release_id})")
            report.add_action(SyncAction(
                action=SyncActionType.SKIP,
                input_record=record,
                release_id=release_id,
                master_id=result.master_id,
                title=result.title,
                artist=result.artist,
                reason="Already in collection",
            ))
        elif result.master_id and result.master_id in current_masters:
            if verbose:
                print_verbose(f"  SKIP (master_id match): {result.artist} - {result.title} (master_id={result.master_id})")
            report.add_action(SyncAction(
                action=SyncActionType.SKIP,
                input_record=record,
                release_id=release_id,
                master_id=result.master_id,
                title=result.title,
                artist=result.artist,
                reason="Already in collection",
            ))
        elif matching_ids:
            report.add_action(SyncAction(
                action=SyncActionType.SKIP,
                input_record=record,
                release_id=release_id,
                master_id=result.master_id,
                title=result.title,
                artist=result.artist,
                reason="Already in collection (fuzzy match)",
            ))
        else:
            if verbose:
                print_verbose(f"  ADD: release_id={release_id} not in collection, master_id={result.master_id} not in masters, no fuzzy match")
            if not dry_run:
                try:
                    if verbose:
                        print_verbose(f"  ADD: {result.artist} - {result.title} (release_id={release_id}) to folder {folder_id}")
                    _add_to_collection(client, release_id, folder_id, limiter)
                except Exception as e:
                    if verbose:
                        print_verbose(f"  ERROR adding release_id={release_id}: {e}")
                    report.add_action(SyncAction(
                        action=SyncActionType.ERROR,
                        input_record=record,
                        release_id=release_id,
                        error=f"Failed to add: {e}",
                    ))
                    continue
            elif verbose:
                print_verbose(f"  ADD (dry run): {result.artist} - {result.title} (release_id={release_id})")

            report.add_action(SyncAction(
                action=SyncActionType.ADD,
                input_record=record,
                release_id=release_id,
                master_id=result.master_id,
                title=result.title,
                artist=result.artist,
                reason="Dry run" if dry_run else None,
            ))

    # Step 4: Remove extras
    if remove_extras:
        if verbose:
            print_verbose(f"Checking extras: {len(extras)} releases in collection not in input")
        for release_id in extras:
            instance_ids = current[release_id]
            for instance_id in instance_ids:
                if not dry_run:
                    try:
                        if verbose:
                            print_verbose(f"  REMOVE: release_id={release_id}, instance_id={instance_id}")
                        _remove_from_collection(client, release_id, instance_id, DEFAULT_READ_FOLDER, limiter)
                    except Exception as e:
                        if verbose:
                            print_verbose(f"  ERROR removing release_id={release_id} instance={instance_id}: {e}")
                        report.add_action(SyncAction(
                            action=SyncActionType.ERROR,
                            release_id=release_id,
                            error=f"Failed to remove instance {instance_id}: {e}",
                        ))
                        continue
                elif verbose:
                    print_verbose(f"  REMOVE (dry run): release_id={release_id}, instance_id={instance_id}")

                report.add_action(SyncAction(
                    action=SyncActionType.REMOVE,
                    release_id=release_id,
                    reason="Not in input file" + (" (dry run)" if dry_run else ""),
                ))

    return report


def add_to_collection(
    client: discogs_client.Client,
    release_id: int | None = None,
    master_id: int | None = None,
    artist: str | None = None,
    album: str | None = None,
    format: str | None = None,
    folder_id: int = DEFAULT_ADD_FOLDER,
    allow_duplicate: bool = False,
    threshold: float = 0.7,
) -> SyncAction:
    """Add a single item to the collection."""
    limiter = get_rate_limiter()

    release_id = _resolve_item(
        client, release_id=release_id, master_id=master_id,
        artist=artist, album=album, format=format, threshold=threshold,
    )

    # Check for duplicates unless allowed
    if not allow_duplicate:
        current, current_masters, current_items = _get_collection_release_ids(client, DEFAULT_READ_FOLDER, limiter)
        if release_id in current or (master_id and master_id in current_masters):
            return SyncAction(
                action=SyncActionType.SKIP,
                release_id=release_id,
                artist=artist,
                title=album,
                reason="Already in collection (use --allow-duplicate to add another copy)",
            )
        if artist and album and _fuzzy_match_items(artist, album, current_items):
            return SyncAction(
                action=SyncActionType.SKIP,
                release_id=release_id,
                artist=artist,
                title=album,
                reason="Already in collection (fuzzy match, use --allow-duplicate to add another copy)",
            )

    _add_to_collection(client, release_id, folder_id, limiter)

    return SyncAction(
        action=SyncActionType.ADD,
        release_id=release_id,
        artist=artist,
        title=album,
    )


def remove_from_collection(
    client: discogs_client.Client,
    release_id: int | None = None,
    artist: str | None = None,
    album: str | None = None,
    format: str | None = None,
    folder_id: int = DEFAULT_READ_FOLDER,
    threshold: float = 0.7,
    confirm: bool = False,
) -> SyncAction:
    """Remove a single item (its first instance) from the collection.

    Without confirm, nothing is removed: raises ConfirmationRequiredError whose
    preview names the exact release and instance that would be removed.
    """
    limiter = get_rate_limiter()

    release_id = _resolve_item(
        client, release_id=release_id, artist=artist, album=album,
        format=format, threshold=threshold,
    )

    current, _, current_items = _get_collection_release_ids(client, folder_id, limiter)
    if release_id not in current:
        return SyncAction(
            action=SyncActionType.SKIP,
            release_id=release_id,
            artist=artist,
            title=album,
            reason="Not in collection",
        )

    # Remove first instance
    instance_id = current[release_id][0]
    copies = len(current[release_id])
    target = describe_release(release_id, current_items, artist, album)
    description = (
        f"{target['artist']} - {target['title']} "
        f"(release_id={release_id}, instance {instance_id}, copies owned: {copies})"
    )
    if not confirm:
        raise ConfirmationRequiredError(
            f"Would remove one copy of {description} from collection. "
            "Re-run with --yes to confirm. No changes were made.",
            preview={
                "action": "remove", "target": "collection", **target,
                "instance_id": instance_id, "folder_id": folder_id, "copies_owned": copies,
            },
        )

    print_info(f"Removing one copy of {description} from collection")
    _remove_from_collection(client, release_id, instance_id, folder_id, limiter)

    return SyncAction(
        action=SyncActionType.REMOVE,
        release_id=release_id,
        artist=target["artist"],
        title=target["title"],
    )


def replace_in_collection(
    client: discogs_client.Client,
    new_release_id: int,
    instance_id: int | None = None,
    old_release_id: int | None = None,
    confirm: bool = False,
) -> list[SyncAction]:
    """Point a collection entry at a different release, keeping its folder, rating, and notes.

    Discogs can't change an instance's release, so this adds new_release_id to the
    old instance's folder, copies rating and custom fields (e.g. media/sleeve
    condition) onto it, then removes the old instance. The old instance is only
    removed once the copy has succeeded.

    Without confirm, nothing changes: raises ConfirmationRequiredError whose
    preview names the old instance, the new release, and what will be carried over.
    """
    limiter = get_rate_limiter()

    old = _find_instance(client, limiter, instance_id=instance_id, release_id=old_release_id)
    if old["release_id"] == new_release_id:
        raise SyncError(f"Instance {old['instance_id']} is already release {new_release_id}. No changes were made.")

    new = _describe_remote_release(client, new_release_id, limiter)
    description = (
        f"{old['artist']} - {old['title']} (release_id={old['release_id']}, instance {old['instance_id']}) "
        f"with {new['artist']} - {new['title']} (release_id={new_release_id})"
    )
    if not confirm:
        raise ConfirmationRequiredError(
            f"Would replace {description}, keeping folder {old['folder_id']}, rating, and "
            f"{len(old['notes'])} note field(s). Re-run with --yes to confirm. No changes were made.",
            preview={
                "action": "replace", "target": "collection",
                "old": {k: old[k] for k in ("release_id", "instance_id", "artist", "title")},
                "new": new,
                "folder_id": old["folder_id"], "rating": old["rating"], "notes": old["notes"],
            },
        )

    print_info(f"Replacing {description}")
    new_instance_id = _add_instance(client, new_release_id, old["folder_id"], limiter)
    try:
        _copy_instance_metadata(client, old["folder_id"], new_release_id, new_instance_id, old["rating"], old["notes"], limiter)
    except Exception as e:
        raise SyncError(
            f"Added release {new_release_id} as instance {new_instance_id}, but copying rating/notes failed: {e}. "
            f"The old instance {old['instance_id']} was NOT removed."
        ) from e
    _remove_from_collection(client, old["release_id"], old["instance_id"], DEFAULT_READ_FOLDER, limiter)

    return [
        SyncAction(action=SyncActionType.ADD, release_id=new_release_id, artist=new["artist"], title=new["title"],
                   reason=f"Replaces instance {old['instance_id']} (new instance {new_instance_id})"),
        SyncAction(action=SyncActionType.REMOVE, release_id=old["release_id"], artist=old["artist"], title=old["title"],
                   reason=f"Replaced by release {new_release_id}"),
    ]


def list_collection(
    client: discogs_client.Client,
    folder_id: int = DEFAULT_READ_FOLDER,
) -> list[CollectionItem]:
    """Fetch and return all collection items from a folder."""
    limiter = get_rate_limiter()
    me = _api_call_with_retry(lambda: client.identity(), limiter)
    folder = _api_call_with_retry(
        lambda: me.collection_folders[folder_id],
        limiter,
    )
    releases = _api_call_with_retry(lambda: folder.releases, limiter)

    items = []
    page_num = 1
    while True:
        try:
            page = _api_call_with_retry(lambda p=page_num: releases.page(p), limiter)
            if not page:
                break
            for item in page:
                release = item.release if hasattr(item, "release") else item
                data = release.data if hasattr(release, "data") else {}

                artist_name = extract_artist_from_data(data)
                album_name = data.get("title", "")

                fmt = None
                formats = data.get("formats", [])
                if formats and isinstance(formats, list):
                    fmt = formats[0].get("name", "") if isinstance(formats[0], dict) else str(formats[0])

                instance_id = getattr(item, "instance_id", None) or data.get("instance_id", 0)
                if hasattr(item, "data") and isinstance(item.data, dict):
                    instance_id = item.data.get("instance_id", instance_id)

                items.append(CollectionItem(
                    instance_id=instance_id,
                    release_id=data.get("id", getattr(release, "id", 0)),
                    master_id=data.get("master_id"),
                    folder_id=folder_id,
                    title=album_name,
                    artist=artist_name,
                    format=fmt,
                    year=data.get("year"),
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


def _get_collection_release_ids(client, folder_id: int, limiter) -> tuple[dict[int, list[int]], dict[int, set[int]], list[tuple[str, str, int]]]:
    """Fetch instances by release, releases by master, and artist/title tuples."""
    me = _api_call_with_retry(lambda: client.identity(), limiter)
    folder = _api_call_with_retry(
        lambda: me.collection_folders[folder_id],
        limiter,
    )
    releases = _api_call_with_retry(lambda: folder.releases, limiter)

    mapping: dict[int, list[int]] = {}
    master_ids: dict[int, set[int]] = {}
    items_info: list[tuple[str, str, int]] = []
    page_num = 1
    while True:
        try:
            page = _api_call_with_retry(lambda p=page_num: releases.page(p), limiter)
            if not page:
                break
            for item in page:
                release = item.release if hasattr(item, "release") else item
                data = release.data if hasattr(release, "data") else {}
                rid = data.get("id") or getattr(release, "id", None)
                instance_id = getattr(item, "instance_id", None) or 0
                if hasattr(item, "data") and isinstance(item.data, dict):
                    instance_id = item.data.get("instance_id", instance_id)
                if rid:
                    mapping.setdefault(rid, []).append(instance_id)
                    artist_name = extract_artist_from_data(data)
                    album_name = data.get("title", "")
                    items_info.append((artist_name, album_name, rid))
                mid = data.get("master_id")
                if mid and rid:
                    master_ids.setdefault(mid, set()).add(rid)
            page_num += 1
        except Exception:
            break

    return mapping, master_ids, items_info


def _fuzzy_match_items(
    artist: str | None,
    title: str | None,
    items: list[tuple[str, str, int]],
    verbose: bool = False,
) -> bool:
    """Check if artist+title fuzzy-matches any item in the list."""
    return bool(_fuzzy_match_release_ids(artist, title, items, verbose))


def _fuzzy_match_release_ids(
    artist: str | None,
    title: str | None,
    items: list[tuple[str, str, int]],
    verbose: bool = False,
) -> set[int]:
    """Return all existing pressings satisfying the fuzzy duplicate check."""
    matches = set()
    if not artist or not title:
        return matches
    for item_artist, item_title, item_rid in items:
        a_sim = _similarity(artist, item_artist)
        t_sim = _similarity(title, item_title)
        if a_sim >= FUZZY_MATCH_THRESHOLD and t_sim >= FUZZY_MATCH_THRESHOLD:
            if verbose:
                print_verbose(
                    f"  SKIP (fuzzy match): '{artist} - {title}' matched '{item_artist} - {item_title}' "
                    f"(release_id={item_rid}, artist_sim={a_sim:.2f}, title_sim={t_sim:.2f})"
                )
            matches.add(item_rid)
    return matches


def _add_to_collection(client, release_id: int, folder_id: int, limiter) -> None:
    """Add a release to a collection folder."""
    me = _api_call_with_retry(lambda: client.identity(), limiter)
    _api_call_with_retry(
        lambda: me.collection_folders[folder_id].add_release(release_id),
        limiter,
    )


def _find_instance(client, limiter, instance_id: int | None = None, release_id: int | None = None) -> dict:
    """Locate one collection instance by instance_id, or by release_id when only one copy is owned."""
    if not instance_id and not release_id:
        raise SyncError("Must provide --instance-id or --old-release-id")

    me = _api_call_with_retry(lambda: client.identity(), limiter)
    folder = _api_call_with_retry(lambda: me.collection_folders[DEFAULT_READ_FOLDER], limiter)
    releases = _api_call_with_retry(lambda: folder.releases, limiter)

    found = []
    page_num = 1
    while True:
        try:
            page = _api_call_with_retry(lambda p=page_num: releases.page(p), limiter)
        except Exception:
            break
        if not page:
            break
        for item in page:
            data = item.data if isinstance(getattr(item, "data", None), dict) else {}
            if instance_id and data.get("instance_id") != instance_id:
                continue
            if release_id and data.get("id") != release_id:
                continue
            info = data.get("basic_information", {})
            found.append({
                "release_id": data.get("id"),
                "instance_id": data.get("instance_id"),
                "folder_id": data.get("folder_id", DEFAULT_ADD_FOLDER),
                "rating": data.get("rating") or 0,
                "notes": [n for n in data.get("notes") or [] if n.get("value")],
                "artist": extract_artist_from_data(info),
                "title": info.get("title", ""),
            })
        page_num += 1

    if not found:
        target = f"instance {instance_id}" if instance_id else f"release {release_id}"
        raise SyncError(f"{target} is not in the collection. No changes were made.")
    if len(found) > 1:
        ids = ", ".join(str(f["instance_id"]) for f in found)
        raise SyncError(f"Release {release_id} has {len(found)} copies (instances {ids}); pass --instance-id to pick one.")
    return found[0]


def _describe_remote_release(client, release_id: int, limiter) -> dict:
    release = _api_call_with_retry(lambda: client.release(release_id), limiter)
    _api_call_with_retry(lambda: release.refresh(), limiter)
    data = release.data
    return {"release_id": release_id, "artist": extract_artist_from_data(data), "title": data.get("title", "")}


def _folder_url(client, folder_id: int, limiter) -> str:
    me = _api_call_with_retry(lambda: client.identity(), limiter)
    return f"{client._base_url}/users/{me.username}/collection/folders/{folder_id}"


def _add_instance(client, release_id: int, folder_id: int, limiter) -> int:
    """Add a release to a folder and return the new instance_id.

    discogs_client's add_release() discards the response, so post directly.
    """
    url = f"{_folder_url(client, folder_id, limiter)}/releases/{release_id}"
    response = _api_call_with_retry(lambda: client._post(url, None), limiter, retries=1)
    return response["instance_id"]


def _copy_instance_metadata(client, folder_id: int, release_id: int, instance_id: int, rating: int, notes: list[dict], limiter) -> None:
    """Set rating and custom field values (media/sleeve condition, notes) on an instance."""
    instance_url = f"{_folder_url(client, folder_id, limiter)}/releases/{release_id}/instances/{instance_id}"
    if rating:
        _api_call_with_retry(lambda: client._post(instance_url, {"rating": rating}), limiter)
    for note in notes:
        url = f"{instance_url}/fields/{note['field_id']}"
        _api_call_with_retry(lambda u=url, v=note["value"]: client._post(u, {"value": v}), limiter)


def _remove_from_collection(client, release_id: int, instance_id: int, folder_id: int, limiter) -> None:
    """Remove a release instance from a collection folder."""
    me = _api_call_with_retry(lambda: client.identity(), limiter)
    instance = CollectionItemInstance(client, {
        "id": release_id, "instance_id": instance_id, "folder_id": folder_id,
    })
    _api_call_with_retry(
        lambda: me.collection_folders[folder_id].remove_release(instance),
        limiter,
    )
