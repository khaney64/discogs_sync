# Discogs Sync

CLI tool to synchronize wantlists and collections with Discogs, and search marketplace pricing.

## Installation

```bash
pip install -e .
```

For development:
```bash
pip install -e ".[dev]"
```

## Setup

### 1. Create a Discogs Application

1. Go to https://www.discogs.com/settings/developers
2. Click "Generate new token" or "Register a new application"
3. Note your **Consumer Key** and **Consumer Secret**

### 2. Authenticate

```bash
discogs-sync auth
```

This will:
- Prompt for your consumer key and secret
- Open a Discogs authorization URL
- Ask you to paste the callback URL after authorizing
- Store tokens in `~/.discogs-sync/config.json`

### 3. Verify

```bash
discogs-sync whoami
```

## Input File Formats

### CSV

Header row required. Columns: `artist` (required), `album` (required), `format`, `year`, `notes`.

```csv
artist,album,format,year,notes
Radiohead,OK Computer,Vinyl,,Must have
Miles Davis,Kind of Blue,,1959,Original pressing
Nirvana,Nevermind,CD,1991,
```

### JSON

Array of objects with the same fields:

```json
[
    {"artist": "Radiohead", "album": "OK Computer", "format": "Vinyl"},
    {"artist": "Miles Davis", "album": "Kind of Blue", "year": 1959}
]
```

### Format Normalization

The following synonyms are automatically normalized:
- `LP`, `record`, `12"`, `12 inch` → **Vinyl**
- `compact disc` → **CD**
- `tape`, `mc` → **Cassette**

## Commands

### Authentication

```bash
discogs-sync auth                          # Run OAuth flow
discogs-sync whoami [--output-format json] # Show authenticated user
```

### Wantlist

```bash
# Batch sync from file
discogs-sync wantlist sync <file> [--remove-extras] [--dry-run] [--threshold 0.7] [--output-format json]

# Add individual items
discogs-sync wantlist add --artist "Radiohead" --album "OK Computer" [--format Vinyl]
discogs-sync wantlist add --master-id 3425
discogs-sync wantlist add --release-id 7890

# Remove items
discogs-sync wantlist remove --artist "Radiohead" --album "OK Computer"
discogs-sync wantlist remove --release-id 7890

# List current wantlist
discogs-sync wantlist list [--output-format json]
```

### Collection

```bash
# Batch sync from file
discogs-sync collection sync <file> [--folder-id 1] [--remove-extras] [--dry-run] [--threshold 0.7] [--output-format json]

# Add individual items
discogs-sync collection add --artist "Radiohead" --album "OK Computer" [--format Vinyl] [--allow-duplicate]
discogs-sync collection add --master-id 3425 [--folder-id 1]
discogs-sync collection add --release-id 7890 [--folder-id 1]

# Remove items
discogs-sync collection remove --artist "Radiohead" --album "OK Computer"
discogs-sync collection remove --release-id 7890

# List collection
discogs-sync collection list [--folder-id 0] [--output-format json]
```

### Marketplace

```bash
# Search by artist/album
discogs-sync marketplace search --artist "Radiohead" --album "OK Computer" [--format Vinyl] [--country US] [--min-price 10] [--max-price 50] [--currency USD] [--output-format json]

# Search by master ID
discogs-sync marketplace search --master-id 3425 [--format Vinyl] [--country US]

# Search by specific release ID (skips master version scan)
discogs-sync marketplace search --release-id 7890

# Batch search from file
discogs-sync marketplace search <file> [--format Vinyl] [--country US] [--min-price N] [--max-price N] [--currency USD] [--max-versions 25] [--output-format json]

# Show detailed progress / condition grade prices
discogs-sync marketplace search --artist "Radiohead" --album "OK Computer" --verbose --details
```

## Options

### Global Options

| Option | Description |
|--------|-------------|
| `--output-format` | `table` (default) or `json` for machine-readable output |
| `--threshold` | Match score threshold 0.0-1.0 (default: 0.7) |
| `--dry-run` | Show what would be done without making changes |

### Wantlist/Collection Options

| Option | Description |
|--------|-------------|
| `--remove-extras` | Remove items not in the input file |
| `--folder-id` | Collection folder ID (default: 1 for adds, 0 for reads) |
| `--allow-duplicate` | Allow adding duplicate copies to collection |

### Marketplace Options

| Option | Description |
|--------|-------------|
| `--format` | Filter versions by format (Vinyl, CD) |
| `--country` | Filter by country of pressing (exact match: US, UK, Germany, etc.) |
| `--release-id` | Fetch stats for a specific release (bypasses master version scan) |
| `--min-price` | Minimum price filter |
| `--max-price` | Maximum price filter |
| `--currency` | Currency code (default: USD) |
| `--max-versions` | Max versions to check per master (default: 25) |
| `--details` | Include suggested prices by condition grade |
| `--verbose` | Show detailed progress and API call logging |

## Release Matching

The tool uses a multi-pass search to match input records to Discogs releases:

1. **Structured search**: Uses artist, album, format, and year
2. **Relaxed search**: Drops format and year constraints
3. **Free text search**: Searches `"artist album"` as plain text

Each result is scored (0.0-1.0) based on:
- 40% artist name similarity
- 40% album title similarity
- 10% year match
- 10% format match

Results below the threshold (default 0.7) are rejected.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Partial failure (some items failed) |
| 2 | Complete failure |

## Running Tests

```bash
pytest
pytest --cov=discogs_sync
```
