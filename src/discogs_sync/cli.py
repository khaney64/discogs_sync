"""Click CLI entry point for discogs-sync."""

from __future__ import annotations

import sys

import click

from .exceptions import AuthenticationError, DiscogsSyncError


def _matches_search(item, query: str) -> bool:
    """Check if search query matches item's artist, title, or year (case-insensitive substring)."""
    q = query.lower()
    artist = (item.artist or "").lower()
    title = (item.title or "").lower()
    year = str(item.year) if getattr(item, "year", None) else ""
    return q in artist or q in title or q in year


@click.group()
@click.version_option(package_name="discogs-sync")
def main():
    """Discogs Sync - synchronize wantlists, collections, and search marketplace."""


# ── Auth commands ──────────────────────────────────────────────────────────


@main.command()
@click.option("--mode", type=click.Choice(["token", "oauth"]), default="token",
              help="Auth method: 'token' for personal access token (default), 'oauth' for OAuth 1.0a flow")
def auth(mode):
    """Authenticate with Discogs.

    Default mode uses a personal access token (generate at discogs.com/settings/developers).
    Use --mode oauth for the full OAuth 1.0a flow with consumer key/secret.
    """
    from .output import console, print_error

    try:
        if mode == "token":
            from .auth import run_token_auth_flow
            result = run_token_auth_flow()
        else:
            from .auth import run_auth_flow
            result = run_auth_flow()
        username = result.get("username", "unknown")
        console.print(f"[green]Authenticated successfully as {username}[/green]")
    except AuthenticationError as e:
        print_error(str(e))
        sys.exit(2)


@main.command()
@click.option("--output-format", type=click.Choice(["table", "json"]), default="table")
def whoami(output_format):
    """Show authenticated user."""
    from .client_factory import build_client
    from .output import output_user_info, print_error
    from .rate_limiter import get_rate_limiter
    from .search import _api_call_with_retry

    try:
        client = build_client()
        limiter = get_rate_limiter()
        identity = _api_call_with_retry(lambda: client.identity(), limiter)
        output_user_info(identity.username, output_format)
    except DiscogsSyncError as e:
        print_error(str(e))
        sys.exit(2)


# ── Wantlist commands ──────────────────────────────────────────────────────


@main.group()
def wantlist():
    """Manage Discogs wantlist."""


@wantlist.command("sync")
@click.argument("file", type=click.Path(exists=True))
@click.option("--remove-extras", is_flag=True, help="Remove wantlist items not in input file")
@click.option("--dry-run", is_flag=True, help="Show what would be done without making changes")
@click.option("--threshold", type=float, default=0.7, help="Match score threshold (0.0-1.0)")
@click.option("--verbose", is_flag=True, help="Print debug information during sync")
@click.option("--output-format", type=click.Choice(["table", "json"]), default="table")
def wantlist_sync(file, remove_extras, dry_run, threshold, verbose, output_format):
    """Batch sync wantlist from CSV/JSON file."""
    from .client_factory import build_client
    from .output import output_sync_report, print_error
    from .parsers import parse_file
    from .sync_wantlist import sync_wantlist

    try:
        records = parse_file(file)
        client = build_client()
        report = sync_wantlist(client, records, remove_extras=remove_extras, dry_run=dry_run, threshold=threshold, verbose=verbose)
        output_sync_report(report, output_format)
        sys.exit(report.exit_code)
    except DiscogsSyncError as e:
        print_error(str(e))
        sys.exit(2)


@wantlist.command("add")
@click.option("--artist", help="Artist name")
@click.option("--album", help="Album title")
@click.option("--format", "fmt", help="Format (Vinyl, CD, Cassette)")
@click.option("--master-id", type=int, help="Discogs master ID")
@click.option("--release-id", type=int, help="Discogs release ID")
@click.option("--threshold", type=float, default=0.7, help="Match score threshold")
@click.option("--output-format", type=click.Choice(["table", "json"]), default="table")
def wantlist_add(artist, album, fmt, master_id, release_id, threshold, output_format):
    """Add a release to the wantlist."""
    from .client_factory import build_client
    from .output import output_sync_report, print_error
    from .models import SyncReport
    from .sync_wantlist import add_to_wantlist

    if not release_id and not master_id and not (artist and album):
        print_error("Provide --release-id, --master-id, or both --artist and --album")
        sys.exit(2)

    try:
        client = build_client()
        action = add_to_wantlist(
            client, release_id=release_id, master_id=master_id,
            artist=artist, album=album, format=fmt, threshold=threshold,
        )
        report = SyncReport(total_input=1)
        report.add_action(action)
        output_sync_report(report, output_format)
        sys.exit(report.exit_code)
    except DiscogsSyncError as e:
        print_error(str(e))
        sys.exit(2)


@wantlist.command("remove")
@click.option("--artist", help="Artist name")
@click.option("--album", help="Album title")
@click.option("--release-id", type=int, help="Discogs release ID")
@click.option("--threshold", type=float, default=0.7, help="Match score threshold")
@click.option("--output-format", type=click.Choice(["table", "json"]), default="table")
def wantlist_remove(artist, album, release_id, threshold, output_format):
    """Remove a release from the wantlist."""
    from .client_factory import build_client
    from .output import output_sync_report, print_error
    from .models import SyncReport
    from .sync_wantlist import remove_from_wantlist

    if not release_id and not (artist and album):
        print_error("Provide --release-id or both --artist and --album")
        sys.exit(2)

    try:
        client = build_client()
        action = remove_from_wantlist(
            client, release_id=release_id, artist=artist, album=album, threshold=threshold,
        )
        report = SyncReport(total_input=1)
        report.add_action(action)
        output_sync_report(report, output_format)
        sys.exit(report.exit_code)
    except DiscogsSyncError as e:
        print_error(str(e))
        sys.exit(2)


@wantlist.command("list")
@click.option("--search", default=None, help="Filter by artist or title (case-insensitive)")
@click.option("--output-format", type=click.Choice(["table", "json"]), default="table")
def wantlist_list(search, output_format):
    """List all wantlist items."""
    from .client_factory import build_client
    from .output import output_wantlist, print_error
    from .sync_wantlist import list_wantlist

    try:
        client = build_client()
        items = list_wantlist(client)
        if search:
            items = [i for i in items if _matches_search(i, search)]
        items.sort(key=lambda i: ((i.artist or "").lower(), (i.title or "").lower()))
        output_wantlist(items, output_format)
    except DiscogsSyncError as e:
        print_error(str(e))
        sys.exit(2)


# ── Collection commands ────────────────────────────────────────────────────


@main.group()
def collection():
    """Manage Discogs collection."""


@collection.command("sync")
@click.argument("file", type=click.Path(exists=True))
@click.option("--folder-id", type=int, default=1, help="Target folder ID (default: 1 Uncategorized)")
@click.option("--remove-extras", is_flag=True, help="Remove collection items not in input file")
@click.option("--dry-run", is_flag=True, help="Show what would be done without making changes")
@click.option("--threshold", type=float, default=0.7, help="Match score threshold (0.0-1.0)")
@click.option("--verbose", is_flag=True, help="Print debug information during sync")
@click.option("--output-format", type=click.Choice(["table", "json"]), default="table")
def collection_sync(file, folder_id, remove_extras, dry_run, threshold, verbose, output_format):
    """Batch sync collection from CSV/JSON file."""
    from .client_factory import build_client
    from .output import output_sync_report, print_error
    from .parsers import parse_file
    from .sync_collection import sync_collection

    try:
        records = parse_file(file)
        client = build_client()
        report = sync_collection(
            client, records, folder_id=folder_id,
            remove_extras=remove_extras, dry_run=dry_run, threshold=threshold,
            verbose=verbose,
        )
        output_sync_report(report, output_format)
        sys.exit(report.exit_code)
    except DiscogsSyncError as e:
        print_error(str(e))
        sys.exit(2)


@collection.command("add")
@click.option("--artist", help="Artist name")
@click.option("--album", help="Album title")
@click.option("--format", "fmt", help="Format (Vinyl, CD, Cassette)")
@click.option("--master-id", type=int, help="Discogs master ID")
@click.option("--release-id", type=int, help="Discogs release ID")
@click.option("--folder-id", type=int, default=1, help="Target folder ID")
@click.option("--allow-duplicate", is_flag=True, help="Allow adding duplicate copies")
@click.option("--threshold", type=float, default=0.7, help="Match score threshold")
@click.option("--output-format", type=click.Choice(["table", "json"]), default="table")
def collection_add(artist, album, fmt, master_id, release_id, folder_id, allow_duplicate, threshold, output_format):
    """Add a release to the collection."""
    from .client_factory import build_client
    from .output import output_sync_report, print_error
    from .models import SyncReport
    from .sync_collection import add_to_collection

    if not release_id and not master_id and not (artist and album):
        print_error("Provide --release-id, --master-id, or both --artist and --album")
        sys.exit(2)

    try:
        client = build_client()
        action = add_to_collection(
            client, release_id=release_id, master_id=master_id,
            artist=artist, album=album, format=fmt,
            folder_id=folder_id, allow_duplicate=allow_duplicate, threshold=threshold,
        )
        report = SyncReport(total_input=1)
        report.add_action(action)
        output_sync_report(report, output_format)
        sys.exit(report.exit_code)
    except DiscogsSyncError as e:
        print_error(str(e))
        sys.exit(2)


@collection.command("remove")
@click.option("--artist", help="Artist name")
@click.option("--album", help="Album title")
@click.option("--release-id", type=int, help="Discogs release ID")
@click.option("--threshold", type=float, default=0.7, help="Match score threshold")
@click.option("--output-format", type=click.Choice(["table", "json"]), default="table")
def collection_remove(artist, album, release_id, threshold, output_format):
    """Remove a release from the collection."""
    from .client_factory import build_client
    from .output import output_sync_report, print_error
    from .models import SyncReport
    from .sync_collection import remove_from_collection

    if not release_id and not (artist and album):
        print_error("Provide --release-id or both --artist and --album")
        sys.exit(2)

    try:
        client = build_client()
        action = remove_from_collection(
            client, release_id=release_id, artist=artist, album=album, threshold=threshold,
        )
        report = SyncReport(total_input=1)
        report.add_action(action)
        output_sync_report(report, output_format)
        sys.exit(report.exit_code)
    except DiscogsSyncError as e:
        print_error(str(e))
        sys.exit(2)


@collection.command("list")
@click.option("--search", default=None, help="Filter by artist or title (case-insensitive)")
@click.option("--folder-id", type=int, default=0, help="Folder ID (default: 0 All)")
@click.option("--output-format", type=click.Choice(["table", "json"]), default="table")
def collection_list(search, folder_id, output_format):
    """List collection items."""
    from .client_factory import build_client
    from .output import output_collection, print_error
    from .sync_collection import list_collection

    try:
        client = build_client()
        items = list_collection(client, folder_id=folder_id)
        if search:
            items = [i for i in items if _matches_search(i, search)]
        items.sort(key=lambda i: ((i.artist or "").lower(), (i.title or "").lower()))
        output_collection(items, output_format)
    except DiscogsSyncError as e:
        print_error(str(e))
        sys.exit(2)


# ── Marketplace commands ───────────────────────────────────────────────────


@main.group()
def marketplace():
    """Search Discogs marketplace."""


@marketplace.command("search")
@click.argument("file", required=False, type=click.Path(exists=True))
@click.option("--artist", help="Artist name")
@click.option("--album", help="Album title")
@click.option("--format", "fmt", help="Format filter (Vinyl, CD)")
@click.option("--master-id", type=int, help="Discogs master ID")
@click.option("--min-price", type=float, help="Minimum price filter")
@click.option("--max-price", type=float, help="Maximum price filter")
@click.option("--currency", default="USD", help="Currency code (default: USD)")
@click.option("--max-versions", type=int, default=25, help="Max versions to check per master")
@click.option("--threshold", type=float, default=0.7, help="Match score threshold")
@click.option("--output-format", type=click.Choice(["table", "json"]), default="table")
def marketplace_search(file, artist, album, fmt, master_id, min_price, max_price, currency, max_versions, threshold, output_format):
    """Search marketplace pricing.

    Provide a CSV/JSON file for batch search, or use --artist/--album or --master-id for individual search.
    """
    from .client_factory import build_client
    from .output import output_marketplace, print_error, print_warning
    from .marketplace import search_marketplace, search_marketplace_batch

    if not file and not master_id and not (artist and album):
        print_error("Provide a file, --master-id, or both --artist and --album")
        sys.exit(2)

    try:
        client = build_client()

        if file:
            from .parsers import parse_file
            records = parse_file(file)
            results, errors = search_marketplace_batch(
                client, records, format=fmt, min_price=min_price, max_price=max_price,
                currency=currency, max_versions=max_versions, threshold=threshold,
            )
            for err in errors:
                print_warning(f"{err['artist']} - {err['album']}: {err['error']}")
        else:
            results = search_marketplace(
                client, master_id=master_id, artist=artist, album=album,
                format=fmt, min_price=min_price, max_price=max_price,
                currency=currency, max_versions=max_versions, threshold=threshold,
            )

        output_marketplace(results, output_format)
    except DiscogsSyncError as e:
        print_error(str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()
