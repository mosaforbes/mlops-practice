"""Utilities for collecting artist data from music streaming platforms.

This module provides high level clients for interacting with the public web
APIs offered by Spotify, Apple Music and YouTube.  Authentication for each
platform requires developer issued API credentials which are usually provided
through OAuth style client id/secret pairs or signed JWT tokens.  The code
below expects those credentials to be provided via the constructor arguments or
through environment variables and intentionally avoids storing persistent
secrets in the source tree.

The clients only implement a small subset of the available endpoints but they
cover the most common operations necessary for gathering artist metadata such as
names, genres, popularity metrics and catalogue highlights.  The classes are
written to be dependency injection friendly by allowing a custom
``requests.Session`` instance to be supplied which makes the code testable
without performing real network requests.
"""
from __future__ import annotations

import base64
import dataclasses
import inspect
import logging
import time
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

import requests


LOGGER = logging.getLogger(__name__)


class MusicPlatformClient:
    """Protocol like base class for music platform clients.

    All concrete implementations should expose a :pyattr:`platform_name`
    attribute and implement :py:meth:`get_artist_profile`.
    """

    platform_name: str

    def get_artist_profile(
        self,
        artist_name: str,
        identifiers: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:  # pragma: no cover - documentation only
        raise NotImplementedError


@dataclasses.dataclass(frozen=True)
class ArtistQuery:
    """Encapsulates identifiers that can help platform lookups.

    Attributes
    ----------
    name:
        The canonical display name of the artist.  This is used as a search
        fallback when a platform specific identifier is not available.
    identifiers:
        Optional mapping of platform specific identifiers such as Spotify
        artist ids or Apple Music artist ids.  Keys should match the platform
        name (``"spotify"``, ``"apple_music"`` or ``"youtube"``) but additional
        keys are ignored by clients.
    storefront:
        Apple Music requires a storefront code to scope catalogue lookups.  The
        default value ``"us"`` is generally a sensible choice.
    """

    name: str
    identifiers: Mapping[str, str] | None = None
    storefront: str = "us"


class SpotifyClient(MusicPlatformClient):
    """Client for the Spotify Web API.

    Parameters
    ----------
    client_id:
        Spotify application client id.
    client_secret:
        Spotify application client secret.
    session:
        Optional :class:`requests.Session` used for HTTP requests.
    token_ttl_buffer:
        Number of seconds to subtract from the official token expiry time in
        order to refresh the token *before* it becomes invalid.  This avoids
        race conditions when multiple requests are made sequentially.
    """

    token_url = "https://accounts.spotify.com/api/token"
    api_base_url = "https://api.spotify.com/v1"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        session: Optional[requests.Session] = None,
        token_ttl_buffer: int = 30,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("Spotify client id and secret must be provided")

        self.client_id = client_id
        self.client_secret = client_secret
        self._session = session or requests.Session()
        self._token_ttl_buffer = token_ttl_buffer
        self._token_expires_at = 0.0
        self._access_token: Optional[str] = None

    @property
    def platform_name(self) -> str:
        return "spotify"

    def get_artist_profile(
        self,
        artist_name: str,
        identifiers: Optional[Mapping[str, str]] = None,
        market: str = "US",
    ) -> Dict[str, Any]:
        """Retrieve artist metadata and top tracks.

        Parameters
        ----------
        artist_name:
            Human readable artist name.  Used for search if no identifier is
            supplied.
        identifiers:
            Optional mapping containing the key ``"spotify"``.  When present the
            associated value is treated as the artist id and no search is
            performed.
        market:
            Market code passed to the top tracks endpoint.  Defaults to ``"US"``.
        """

        artist_id = (identifiers or {}).get(self.platform_name)
        if artist_id:
            artist_data = self._request("GET", f"/artists/{artist_id}")
        else:
            artist_data = self._search_artist_by_name(artist_name)
            artist_id = artist_data.get("id")

        top_tracks = (
            self._request("GET", f"/artists/{artist_id}/top-tracks", params={"market": market})
            if artist_id
            else {"tracks": []}
        )

        return {
            "artist": artist_data,
            "top_tracks": top_tracks.get("tracks", []),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_token(self) -> str:
        current_time = time.time()
        if self._access_token and current_time < self._token_expires_at:
            return self._access_token

        LOGGER.debug("Refreshing Spotify access token")
        encoded_credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode("utf-8")
        ).decode("ascii")

        response = self._session.post(
            self.token_url,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {encoded_credentials}"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()

        expires_in = payload.get("expires_in", 3600)
        self._access_token = payload["access_token"]
        self._token_expires_at = current_time + max(0, expires_in - self._token_ttl_buffer)
        return self._access_token

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        token = self._ensure_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("Accept", "application/json")

        response = self._session.request(
            method,
            f"{self.api_base_url}{path}",
            headers=headers,
            timeout=30,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def _search_artist_by_name(self, artist_name: str) -> Dict[str, Any]:
        payload = self._request(
            "GET",
            "/search",
            params={"q": artist_name, "type": "artist", "limit": 1},
        )
        items = payload.get("artists", {}).get("items", [])
        if not items:
            raise LookupError(f"Spotify artist '{artist_name}' not found")
        return items[0]


class AppleMusicClient(MusicPlatformClient):
    """Client for the Apple Music API.

    Parameters
    ----------
    developer_token:
        A signed JWT generated from an Apple Music developer account.
    user_token:
        Optional MusicKit user token.  Required for accessing library data but
        not for public catalogue lookups.
    session:
        Optional :class:`requests.Session` used for HTTP requests.
    """

    api_base_url = "https://api.music.apple.com/v1"

    def __init__(
        self,
        developer_token: str,
        *,
        user_token: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not developer_token:
            raise ValueError("Apple Music developer token must be provided")

        self.developer_token = developer_token
        self.user_token = user_token
        self._session = session or requests.Session()

    @property
    def platform_name(self) -> str:
        return "apple_music"

    def get_artist_profile(
        self,
        artist_name: str,
        identifiers: Optional[Mapping[str, str]] = None,
        storefront: str = "us",
    ) -> Dict[str, Any]:
        artist_id = (identifiers or {}).get(self.platform_name)
        if artist_id:
            artist = self._catalog_request(
                f"/catalog/{storefront}/artists/{artist_id}", params={"include": "albums"}
            )
        else:
            artist = self._search_artist_by_name(artist_name, storefront=storefront)
            artist_id = artist.get("id")
            if artist_id:
                artist = self._catalog_request(
                    f"/catalog/{storefront}/artists/{artist_id}", params={"include": "albums"}
                )

        data = artist.get("data", [])
        first_item = data[0] if data else {}
        relationships = first_item.get("relationships", {})
        albums = relationships.get("albums", {}).get("data", [])
        return {
            "artist": first_item,
            "albums": albums,
        }

    def _catalog_request(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.developer_token}",
            "Accept": "application/json",
        }
        if self.user_token:
            headers["Music-User-Token"] = self.user_token

        response = self._session.get(
            f"{self.api_base_url}{path}",
            headers=headers,
            timeout=30,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def _search_artist_by_name(self, artist_name: str, storefront: str) -> Dict[str, Any]:
        payload = self._catalog_request(
            f"/catalog/{storefront}/search",
            params={"term": artist_name, "types": "artists", "limit": 1},
        )
        artists = payload.get("results", {}).get("artists", {}).get("data", [])
        if not artists:
            raise LookupError(f"Apple Music artist '{artist_name}' not found")
        return {"data": artists}


class YouTubeMusicClient(MusicPlatformClient):
    """Client for the YouTube Data API focused on music channels."""

    search_url = "https://www.googleapis.com/youtube/v3/search"
    channels_url = "https://www.googleapis.com/youtube/v3/channels"

    def __init__(
        self,
        api_key: str,
        *,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not api_key:
            raise ValueError("YouTube API key must be provided")

        self.api_key = api_key
        self._session = session or requests.Session()

    @property
    def platform_name(self) -> str:
        return "youtube"

    def get_artist_profile(
        self,
        artist_name: str,
        identifiers: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        channel_id = (identifiers or {}).get(self.platform_name)
        if not channel_id:
            channel_id = self._search_channel_id(artist_name)

        channel_info = self._request(
            self.channels_url,
            params={
                "part": "snippet,statistics,topicDetails",
                "id": channel_id,
                "key": self.api_key,
            },
        )
        items = channel_info.get("items", [])
        if not items:
            raise LookupError(f"YouTube channel '{channel_id}' not found")
        return items[0]

    def _search_channel_id(self, artist_name: str) -> str:
        payload = self._request(
            self.search_url,
            params={
                "part": "snippet",
                "q": artist_name,
                "type": "channel",
                "maxResults": 1,
                "key": self.api_key,
            },
        )
        items = payload.get("items", [])
        if not items:
            raise LookupError(f"YouTube artist '{artist_name}' not found")
        return items[0]["id"]["channelId"]

    def _request(self, url: str, *, params: MutableMapping[str, Any]) -> Dict[str, Any]:
        response = self._session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()


class ArtistDataAggregator:
    """Fetches artist information from multiple streaming platforms.

    The aggregator drives one or more :class:`MusicPlatformClient` instances and
    collates their responses in a dictionary that exposes both the successful
    payloads and any errors that occurred.  This makes it straightforward to use
    in data pipelines where partial success is acceptable (e.g. the artist might
    exist on Spotify but not on Apple Music).
    """

    def __init__(self, clients: Iterable[MusicPlatformClient], *, logger: Optional[logging.Logger] = None) -> None:
        self._clients = list(clients)
        self._logger = logger or LOGGER

    def aggregate(self, query: ArtistQuery) -> Dict[str, Any]:
        """Return a combined view of artist data across platforms."""

        payload: Dict[str, Any] = {"artist": query.name, "results": {}, "errors": {}}
        identifiers = query.identifiers or {}

        for client in self._clients:
            platform = client.platform_name
            try:
                self._logger.debug("Fetching %s data for '%s'", platform, query.name)
                call_params = {
                    "artist_name": query.name,
                    "identifiers": identifiers,
                }

                signature = inspect.signature(client.get_artist_profile)
                if "storefront" in signature.parameters:
                    call_params["storefront"] = query.storefront

                payload["results"][platform] = client.get_artist_profile(**call_params)
            except Exception as exc:  # pragma: no cover - exercised via tests
                self._logger.warning("Failed to fetch %s data: %s", platform, exc)
                payload["errors"][platform] = str(exc)

        return payload


__all__ = [
    "ArtistDataAggregator",
    "ArtistQuery",
    "AppleMusicClient",
    "MusicPlatformClient",
    "SpotifyClient",
    "YouTubeMusicClient",
]
