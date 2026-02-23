"""Entry-point script for running discogs-sync without pip install."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from discogs_sync.cli import main

main()
