# bart-eta -- loominum example driver

A small example showing how to use loominum's CDP plumbing to scrape a page
that **can't be fetched** with a plain HTTP client.

BART's real-time ETA page (`/schedules/eta/<STATION>`) returns a valid HTML
shell to a `curl` request -- but the actual departure times are hydrated
client-side via JS after page load. A plain HTTP fetch gets the menu
chrome and zero ETAs. You need a real browser to load the JS and let the
`.schedule-platforms` container hydrate.

This example also demonstrates the **`loominum[fetch]` optional extra**, used
for the HTML-to-text rendering fallback.

## Install

```
pip install -e .
# (this pulls in loominum + loominum[fetch] from the parent loominum repo)
```

Start Chrome with the debug port enabled:

```
chrome --remote-debugging-port=9222
# or chromium / google-chrome / Edge -- any Chromium browser supporting CDP
```

## Usage

```
# Departures from Embarcadero
bart-eta --station EMBR

# JSON output
bart-eta --station 12TH --format json

# Print every station code with full name
bart-eta --list-stations
```

Example output:

```
$ bart-eta --station EMBR
BART real-time departures -- Embarcadero (EMBR)
  source: https://www.bart.gov/schedules/eta/EMBR

  Platform 1:
    Daly City                    7 min (6c), 27 min (6c), 47 min (6c)
    Millbrae                     12 min (6c), 32 min (6c), 52 min (8c)
    SF Airport                   5 min (9c), 16 min (9c), 24 min (9c)
  Platform 2:
    Antioch                      9 min (9c), 29 min (9c), 49 min (9c)
    Richmond                     4 min (6c), 26 min (6c), 43 min (6c)
    ...
```

## What this demonstrates

- **CDP page navigation** -- drive an existing Chrome session to load a URL.
- **Polling for hydrated content** -- wait for client-side JS to populate the
  `.schedule-platforms` container before grabbing the snapshot.
- **Structured DOM extraction** -- pick the smallest container that has all
  the data, return its inner text to the Python side, parse cleanly there.
- **The `loominum[fetch]` optional extra** for HTML-to-text rendering when
  needed.
- **Graceful degradation** -- if `loominum[fetch]` isn't installed, the
  driver still works using the raw text path.

## Why a browser at all?

Run this to convince yourself:

```
curl -s 'https://www.bart.gov/schedules/eta/EMBR' | grep -c 'min'
# 0
```

The HTML shell has zero "min" tokens. The ETAs only exist after JS runs.
A bare HTTP client can't get them; a CDP-driven browser can.

## License

Apache-2.0
