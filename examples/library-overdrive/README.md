# library-overdrive -- loominum example driver

Search a library's OverDrive catalog and report which titles are available
for immediate borrow vs. on hold. Works against any library with an
OverDrive subdomain (thousands of US public libraries -- NYPL, BPL, SFPL,
LAPL, CCC, etc.).

## Why a browser?

OverDrive's catalog grid hydrates client-side after page load -- a plain
HTTP fetch returns the SSR shell with sidebars and facets but no title
cards. The actual `<li class="js-titleCard">` elements appear only after
JS runs against the user's library session. CDP-driven Chrome reaches the
data the way a human browser would.

## Install

```
pip install -e .
# pulls in loominum from the parent loominum repo
```

Start Chrome with the debug port enabled:

```
chrome --remote-debugging-port=9222
```

## Usage

```
# Search NYPL for Dune
library-overdrive --library nypl --query "dune"

# Available-right-now filter (drop hold-list items)
library-overdrive --library sfpl --query "ursula k le guin" --available-only

# JSON output
library-overdrive --library bpl --query "the corrections" --format json
```

Example output:

```
$ library-overdrive --library nypl --query "dune"
Library OverDrive search -- nypl: "dune"
  source: https://nypl.overdrive.com/search?query=dune
  24 result(s) shown

  [available]    Dune -- Frank Herbert  (Audiobook)
  [on hold]      Dune -- Frank Herbert  (Ebook)  [Wait list: 23 weeks]
  [available]    Dune -- Frank Herbert  (Ebook)
  [on hold]      Dune Messiah -- Frank Herbert  (Ebook)  [Wait list: 8 weeks]
  ...
```

## Finding your library's subdomain

Most US public libraries have an OverDrive subdomain like
`<key>.overdrive.com`. Common examples:

| Library | Key |
|---|---|
| New York Public Library | `nypl` |
| Brooklyn Public Library | `bklynlibrary` |
| San Francisco Public Library | `sfpl` |
| Los Angeles Public Library | `lapl` |
| Chicago Public Library | `cpl` |
| Boston Public Library | `bpl` |
| Seattle Public Library | `seattle` |

If your library uses Libby (newer UI), the OverDrive subdomain still works
in most cases -- Libby is a frontend over the same OverDrive backend.

## License

Apache-2.0
