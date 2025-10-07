---
challenge:
  module: Data Collection
  challenge: Dummy Artist Aggregation Harness
  type: Guide
---

# Dummy Artist Aggregation Harness

The streaming platform clients in `src/data_collection/music_platform_clients.py`
expect real API credentials.  To help you understand how the
`ArtistDataAggregator` orchestrates those clients without making any network
calls, this guide ships with a ready-to-run dummy dataset and mock client
implementations.

## Running the harness

The script lives at `experimentation/run_dummy_music_aggregator.py`.  Use it to
inspect the aggregator output for an in-memory dataset:

```bash
python experimentation/run_dummy_music_aggregator.py --list-artists
python experimentation/run_dummy_music_aggregator.py --artist "Neon Trees"
```

If you omit `--artist`, the script uses the first configured dummy artist.  All
payloads are generated locally so you can safely run the script without valid
API credentials or an internet connection.

## How it works

The harness defines lightweight subclasses of `MusicPlatformClient` that return
pre-canned payloads for Spotify, Apple Music, and YouTube.  They honour the same
method signatures as the real clients, including Apple Music's storefront
parameter, so you can exercise identifier and storefront handling behaviour.

## Extending the dataset

To add another artist for experimentation:

1. Duplicate one of the entries inside `DUMMY_ARTISTS` in the script.
2. Update the identifiers and payload snippets to match the scenario you want to
   test.
3. Run the script with `--artist "Your New Artist"` to validate the aggregator
   behaviour.

The script deep copies payloads returned from the dataset which makes it safe to
mutate the aggregated results in a debugger or REPL without affecting subsequent
runs.
