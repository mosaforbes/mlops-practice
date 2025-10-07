"""Run the artist data aggregator against dummy in-memory datasets.

This script exists as a quick manual test harness for
:class:`ArtistDataAggregator`.  It uses lightweight mock client
implementations that implement the :class:`MusicPlatformClient` protocol but
return static data instead of calling the real streaming platform APIs.  The
behaviour matches the real aggregator which makes it useful for validating that
identifiers and storefront handling work as expected without requiring network
access or credentials.

Usage
-----
.. code-block:: bash

    python experimentation/run_dummy_music_aggregator.py --artist "Neon Trees"

You can list available dummy artists using ``--list-artists``.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, MutableMapping

from src.data_collection.music_platform_clients import (
    ArtistDataAggregator,
    ArtistQuery,
    MusicPlatformClient,
)


@dataclass(frozen=True)
class DummyArtist:
    """Container for the mocked payloads per platform."""

    name: str
    identifiers: Mapping[str, str]
    storefront: str
    payloads: Mapping[str, MutableMapping[str, Any]]


# ---------------------------------------------------------------------------
# Dummy datasets
# ---------------------------------------------------------------------------
DUMMY_ARTISTS: Dict[str, DummyArtist] = {
    "neon trees": DummyArtist(
        name="Neon Trees",
        storefront="us",
        identifiers={
            "spotify": "dummy-spotify-id-neon-trees",
            "apple_music": "dummy-apple-id-neon-trees",
            "youtube": "UC_dummy_neon_trees",
        },
        payloads={
            "spotify": {
                "artist": {
                    "id": "dummy-spotify-id-neon-trees",
                    "name": "Neon Trees",
                    "genres": ["alt-rock", "indie pop"],
                    "popularity": 73,
                },
                "top_tracks": [
                    {"name": "Everybody Talks", "popularity": 85},
                    {"name": "Animal", "popularity": 78},
                ],
            },
            "apple_music": {
                "id": "dummy-apple-id-neon-trees",
                "type": "artists",
                "attributes": {
                    "name": "Neon Trees",
                    "genreNames": ["Alternative"],
                    "url": "https://music.apple.com/us/artist/neon-trees/123",
                },
            },
            "youtube": {
                "id": "UC_dummy_neon_trees",
                "snippet": {
                    "title": "Neon Trees",
                    "description": "Official Neon Trees channel (dummy data)",
                },
                "statistics": {"subscriberCount": "320000", "videoCount": "152"},
            },
        },
    ),
    "glass animals": DummyArtist(
        name="Glass Animals",
        storefront="gb",
        identifiers={
            "spotify": "dummy-spotify-id-glass-animals",
            "apple_music": "dummy-apple-id-glass-animals",
            "youtube": "UC_dummy_glass_animals",
        },
        payloads={
            "spotify": {
                "artist": {
                    "id": "dummy-spotify-id-glass-animals",
                    "name": "Glass Animals",
                    "genres": ["indie pop", "electropop"],
                    "popularity": 80,
                },
                "top_tracks": [
                    {"name": "Heat Waves", "popularity": 95},
                    {"name": "Gooey", "popularity": 82},
                ],
            },
            "apple_music": {
                "id": "dummy-apple-id-glass-animals",
                "type": "artists",
                "attributes": {
                    "name": "Glass Animals",
                    "genreNames": ["Alternative"],
                    "url": "https://music.apple.com/gb/artist/glass-animals/456",
                },
            },
            "youtube": {
                "id": "UC_dummy_glass_animals",
                "snippet": {
                    "title": "Glass Animals",
                    "description": "Official Glass Animals channel (dummy data)",
                },
                "statistics": {"subscriberCount": "840000", "videoCount": "214"},
            },
        },
    ),
}


# ---------------------------------------------------------------------------
# Dummy client implementations
# ---------------------------------------------------------------------------
class DummyStaticClient(MusicPlatformClient):
    """Return static data for a platform to mimic API responses."""

    def __init__(self, platform_name: str, data: Mapping[str, Any]) -> None:
        self._platform_name = platform_name
        self._data = data

    @property
    def platform_name(self) -> str:
        return self._platform_name

    def get_artist_profile(
        self, artist_name: str, identifiers: Mapping[str, str] | None = None, **_: Any
    ) -> Dict[str, Any]:
        key = (identifiers or {}).get(self.platform_name, artist_name.lower())
        try:
            payload = self._data[key]
        except KeyError:
            raise LookupError(
                f"No dummy payload for artist '{artist_name}' on {self.platform_name}"
            ) from None
        return json.loads(json.dumps(payload))  # deep copy for realism


class DummyAppleMusicClient(DummyStaticClient):
    """Apple Music dummy client adds storefront handling."""

    def get_artist_profile(
        self,
        artist_name: str,
        identifiers: Mapping[str, str] | None = None,
        storefront: str = "us",
    ) -> Dict[str, Any]:
        payload = super().get_artist_profile(artist_name, identifiers)
        payload.setdefault("storefront", storefront)
        return payload


# ---------------------------------------------------------------------------
# Script helpers
# ---------------------------------------------------------------------------

def build_dummy_clients(artist: DummyArtist) -> Iterable[MusicPlatformClient]:
    """Create dummy platform clients bound to a specific artist."""

    def keyed_payloads(platform: str) -> Dict[str, Any]:
        key = artist.identifiers.get(platform, artist.name.lower())
        return {key: artist.payloads[platform]}

    return (
        DummyStaticClient("spotify", keyed_payloads("spotify")),
        DummyAppleMusicClient("apple_music", keyed_payloads("apple_music")),
        DummyStaticClient("youtube", keyed_payloads("youtube")),
    )


def list_artists() -> str:
    lines = ["Available dummy artists:"]
    for dummy in DUMMY_ARTISTS.values():
        lines.append(f"  - {dummy.name} (storefront: {dummy.storefront})")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artist",
        type=str,
        help="Name of the artist to load. Defaults to the first configured artist.",
    )
    parser.add_argument(
        "--list-artists",
        action="store_true",
        help="List available dummy artists and exit.",
    )
    args = parser.parse_args()

    if args.list_artists:
        print(list_artists())
        return

    artist_name = (args.artist or next(iter(DUMMY_ARTISTS.values())).name).lower()
    try:
        artist = DUMMY_ARTISTS[artist_name]
    except KeyError:
        parser.error(f"Unknown artist '{args.artist}'. Use --list-artists to inspect options.")
        return

    aggregator = ArtistDataAggregator(build_dummy_clients(artist))
    query = ArtistQuery(
        name=artist.name,
        identifiers=artist.identifiers,
        storefront=artist.storefront,
    )
    payload = aggregator.aggregate(query)

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
