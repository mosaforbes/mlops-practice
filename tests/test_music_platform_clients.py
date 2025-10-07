import pytest

from src.data_collection.music_platform_clients import (
    ArtistDataAggregator,
    ArtistQuery,
    MusicPlatformClient,
)


class DummyClient(MusicPlatformClient):
    platform_name = "dummy"

    def __init__(self) -> None:
        self.calls = []

    def get_artist_profile(self, artist_name, identifiers=None):
        self.calls.append((artist_name, identifiers))
        return {"artist": artist_name, "identifiers": identifiers}


class DummyStorefrontClient(MusicPlatformClient):
    platform_name = "apple_music"

    def __init__(self) -> None:
        self.received_storefront = None

    def get_artist_profile(self, artist_name, identifiers=None, storefront="us"):
        self.received_storefront = storefront
        return {"artist": artist_name, "storefront": storefront}


class FailingClient(MusicPlatformClient):
    platform_name = "failing"

    def get_artist_profile(self, artist_name, identifiers=None):
        raise RuntimeError("boom")


def test_aggregator_collects_results_and_errors():
    dummy = DummyClient()
    storefront_client = DummyStorefrontClient()
    aggregator = ArtistDataAggregator([dummy, storefront_client, FailingClient()])

    identifiers = {"dummy": "123"}
    query = ArtistQuery(name="Test Artist", identifiers=identifiers, storefront="gb")
    payload = aggregator.aggregate(query)

    assert payload["artist"] == "Test Artist"
    assert payload["results"]["dummy"]["artist"] == "Test Artist"
    assert payload["results"]["dummy"]["identifiers"] == identifiers
    assert payload["results"]["apple_music"]["storefront"] == "gb"
    assert "failing" in payload["errors"]
    assert payload["errors"]["failing"] == "boom"

    # Ensure that the storefront aware client actually received the storefront
    assert storefront_client.received_storefront == "gb"

    # The original identifiers mapping should not be modified by the aggregator
    assert identifiers == {"dummy": "123"}
