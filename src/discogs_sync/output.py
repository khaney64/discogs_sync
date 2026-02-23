"""Rich table and JSON output formatting."""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()
error_console = Console(stderr=True)


def output_json(data: Any) -> None:
    """Write JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def output_table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    """Display a Rich table."""
    table = Table(title=title)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*row)
    console.print(table)


def output_sync_report(report, output_format: str = "table") -> None:
    """Output a SyncReport in the requested format."""
    from .models import SyncActionType

    if output_format == "json":
        output_json(report.to_dict())
        return

    # Summary
    console.print(f"\n[bold]Sync Report[/bold]")
    console.print(f"  Total input: {report.total_input}")
    console.print(f"  Added:   [green]{report.added}[/green]")
    console.print(f"  Removed: [yellow]{report.removed}[/yellow]")
    console.print(f"  Skipped: [dim]{report.skipped}[/dim]")
    console.print(f"  Errors:  [red]{report.errors}[/red]")

    # Details
    if report.actions:
        table = Table(title="Actions")
        table.add_column("Action", style="bold")
        table.add_column("Artist")
        table.add_column("Title")
        table.add_column("Release ID")
        table.add_column("Details")
        for a in report.actions:
            artist = a.artist or (a.input_record.artist if a.input_record else "")
            title = a.title or (a.input_record.album if a.input_record else "")
            release = str(a.release_id) if a.release_id else ""
            detail = a.reason or a.error or ""
            style_map = {
                SyncActionType.ADD: "green",
                SyncActionType.REMOVE: "yellow",
                SyncActionType.SKIP: "dim",
                SyncActionType.ERROR: "red",
            }
            style = style_map.get(a.action, "")
            table.add_row(
                f"[{style}]{a.action.value}[/{style}]",
                artist,
                title,
                release,
                detail,
            )
        console.print(table)


def output_wantlist(items: list, output_format: str = "table") -> None:
    """Output wantlist items."""
    if output_format == "json":
        output_json({"items": [item.to_dict() for item in items], "total": len(items)})
        return

    table = Table(title="Wantlist")
    table.add_column("Release ID")
    table.add_column("Master ID")
    table.add_column("Artist")
    table.add_column("Title")
    table.add_column("Format")
    table.add_column("Year")
    for item in items:
        table.add_row(
            str(item.release_id),
            str(item.master_id or ""),
            item.artist or "",
            item.title or "",
            item.format or "",
            str(item.year or ""),
        )
    console.print(table)
    console.print(f"\nTotal: {len(items)}")


def output_collection(items: list, output_format: str = "table") -> None:
    """Output collection items."""
    if output_format == "json":
        output_json({"items": [item.to_dict() for item in items], "total": len(items)})
        return

    table = Table(title="Collection")
    table.add_column("Instance ID")
    table.add_column("Release ID")
    table.add_column("Master ID")
    table.add_column("Folder ID")
    table.add_column("Artist")
    table.add_column("Title")
    table.add_column("Format")
    table.add_column("Year")
    for item in items:
        table.add_row(
            str(item.instance_id),
            str(item.release_id),
            str(item.master_id or ""),
            str(item.folder_id),
            item.artist or "",
            item.title or "",
            item.format or "",
            str(item.year or ""),
        )
    console.print(table)
    console.print(f"\nTotal: {len(items)}")


def output_marketplace(results: list, output_format: str = "table") -> None:
    """Output marketplace search results."""
    if output_format == "json":
        output_json({"results": [r.to_dict() for r in results], "total": len(results)})
        return

    table = Table(title="Marketplace Results")
    table.add_column("Master ID")
    table.add_column("Release ID")
    table.add_column("Artist")
    table.add_column("Title")
    table.add_column("Format")
    table.add_column("Country")
    table.add_column("Year")
    table.add_column("For Sale", justify="right")
    table.add_column("Lowest Price", justify="right")
    for r in results:
        price_str = f"{r.lowest_price:.2f} {r.currency}" if r.lowest_price is not None else "N/A"
        table.add_row(
            str(r.master_id or ""),
            str(r.release_id or ""),
            r.artist or "",
            r.title or "",
            r.format or "",
            r.country or "",
            str(r.year or ""),
            str(r.num_for_sale),
            price_str,
        )
    console.print(table)
    console.print(f"\nTotal: {len(results)}")


def output_user_info(username: str, output_format: str = "table") -> None:
    """Output authenticated user info."""
    if output_format == "json":
        output_json({"username": username})
        return

    console.print(f"Authenticated as: [bold]{username}[/bold]")


def print_error(message: str) -> None:
    """Print an error message to stderr."""
    error_console.print(f"[red]Error:[/red] {message}")


def print_warning(message: str) -> None:
    """Print a warning to stderr."""
    error_console.print(f"[yellow]Warning:[/yellow] {message}")


def print_info(message: str) -> None:
    """Print an info message to stderr."""
    error_console.print(f"[blue]Info:[/blue] {message}")
