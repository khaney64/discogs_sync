"""Entry-point script for running discogs-sync without pip install."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Pre-flight dependency check — report all missing packages at once.
_REQUIRED_PACKAGES = {
    "discogs_client": "python3-discogs-client",
    "click": "click",
    "rich": "rich",
}

_missing = []
for _module, _pip_name in _REQUIRED_PACKAGES.items():
    try:
        __import__(_module)
    except ImportError:
        _missing.append(_pip_name)

if _missing:
    print(
        f"Error: missing required packages: {', '.join(_missing)}\n"
        f"Install them with:  pip install {' '.join(_missing)}",
        file=sys.stderr,
    )
    sys.exit(2)

from discogs_sync.cli import main

main()
