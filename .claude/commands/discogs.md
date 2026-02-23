---
description: Manage Discogs wantlist, collection, and marketplace search
allowed-tools: Bash, Read, Write, Glob, Grep
---

# Discogs Sync Tool

You have access to the `python discogs-sync.py` CLI tool for managing Discogs wantlists, collections, and searching marketplace pricing.

## Available Commands

### Authentication
- `python discogs-sync.py whoami --output-format json` — Check authenticated user

### Wantlist
- `python discogs-sync.py wantlist list --output-format json` — List all wantlist items
- `python discogs-sync.py wantlist add --artist "ARTIST" --album "ALBUM" [--format Vinyl|CD|Cassette]` — Add to wantlist
- `python discogs-sync.py wantlist add --release-id ID` — Add by release ID
- `python discogs-sync.py wantlist add --master-id ID` — Add by master ID
- `python discogs-sync.py wantlist remove --artist "ARTIST" --album "ALBUM"` — Remove from wantlist
- `python discogs-sync.py wantlist remove --release-id ID` — Remove by release ID
- `python discogs-sync.py wantlist sync FILE [--dry-run] [--remove-extras] --output-format json` — Batch sync from CSV/JSON

### Collection
- `python discogs-sync.py collection list [--folder-id 0] --output-format json` — List collection
- `python discogs-sync.py collection add --artist "ARTIST" --album "ALBUM" [--format Vinyl] [--allow-duplicate]` — Add to collection
- `python discogs-sync.py collection add --release-id ID [--folder-id 1]` — Add by release ID
- `python discogs-sync.py collection remove --artist "ARTIST" --album "ALBUM"` — Remove from collection
- `python discogs-sync.py collection remove --release-id ID` — Remove by release ID
- `python discogs-sync.py collection sync FILE [--dry-run] [--remove-extras] --output-format json` — Batch sync

### Marketplace
- `python discogs-sync.py marketplace search --artist "ARTIST" --album "ALBUM" [--format Vinyl] [--min-price N] [--max-price N] --output-format json` — Search pricing
- `python discogs-sync.py marketplace search --master-id ID [--format Vinyl] --output-format json` — Search by master ID
- `python discogs-sync.py marketplace search FILE [--format Vinyl] [--max-price N] --output-format json` — Batch search

## Input File Formats

CSV (header: artist,album,format,year,notes) or JSON (array of objects with same fields). `artist` and `album` are required.

## Usage Guidelines

1. Always use `--output-format json` when parsing results programmatically
2. Use `--dry-run` before sync operations to preview changes
3. For batch operations, create a CSV or JSON file first
4. The tool rate-limits automatically to stay within Discogs API limits
5. Match threshold defaults to 0.7 — lower it with `--threshold 0.5` for fuzzy matches

## Interpreting JSON Output

Sync report JSON:
```json
{"summary": {"total_input": N, "added": N, "removed": N, "skipped": N, "errors": N}, "actions": [...]}
```

Marketplace JSON:
```json
{"results": [{"master_id": N, "release_id": N, "title": "...", "artist": "...", "format": "...", "num_for_sale": N, "lowest_price": N.NN, "currency": "USD"}], "total": N}
```

When the user asks you to interact with Discogs (add/remove from wantlist or collection, search marketplace, etc.), use the appropriate command above. Parse JSON output to provide a clear summary to the user.
