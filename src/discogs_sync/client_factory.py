"""Build authenticated Discogs Client instances."""

from __future__ import annotations

import discogs_client

from .auth import USER_AGENT, check_auth
from .exceptions import AuthenticationError


def build_client() -> discogs_client.Client:
    """Build an authenticated Discogs client from stored tokens.

    Raises AuthenticationError if no tokens are stored.
    """
    tokens = check_auth()
    if not tokens:
        raise AuthenticationError(
            "Not authenticated. Run 'discogs-sync auth' first."
        )

    client = discogs_client.Client(
        USER_AGENT,
        consumer_key=tokens["consumer_key"],
        consumer_secret=tokens["consumer_secret"],
        token=tokens["access_token"],
        secret=tokens["access_token_secret"],
    )
    return client
