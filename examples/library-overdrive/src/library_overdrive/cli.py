"""Library OverDrive availability check -- a loominum example driver.

Search a library's OverDrive catalog for a title and report which copies are
available now vs. on hold. Works against any library with an OverDrive
subdomain (thousands of US public libraries, including NYPL, BPL, SFPL,
LAPL, etc.).

OverDrive uses an auth/session model + JS-rendered grid; a plain HTTP fetch
returns the SSR shell without the title cards. Driving a real browser is
how a user would actually browse, and is how the driver reaches the data.

Usage:
    library-overdrive --library nypl --query "dune"
    library-overdrive --library sfpl --query "ursula k le guin" --format json
"""
from __future__ import annotations
import argparse
import asyncio
import json
import re
import sys
import urllib.parse
import urllib.request

import websockets


# ---------- CDP plumbing (minimal -- loominum has a richer client) ----------

async def _cdp_send(ws, mid, method, params=None):
    msg = {"id": mid, "method": method}
    if params:
        msg["params"] = params
    await ws.send(json.dumps(msg))
    while True:
        r = json.loads(await ws.recv())
        if r.get("id") == mid:
            return r


def _list_pages(host: str, port: int) -> list[dict]:
    req = urllib.request.Request(f"http://{host}:{port}/json",
                                 headers={"Host": "localhost"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _pick_page(pages: list[dict], library: str) -> dict:
    """Prefer an existing tab on this library's OverDrive subdomain."""
    domain = f"{library}.overdrive.com"
    for p in pages:
        if p.get("type") == "page" and domain in p.get("url", ""):
            return p
    for p in pages:
        if p.get("type") == "page" and p.get("url", "") == "about:blank":
            return p
    for p in pages:
        if p.get("type") == "page":
            return p
    raise RuntimeError("no Chrome page tab available")


def _ws_url(page: dict, host: str, port: int) -> str:
    raw = page["webSocketDebuggerUrl"]
    return re.sub(r"://(localhost|127\.0\.0\.1)(:\d+)?",
                  f"://{host}:{port}", raw, count=1)


# ---------- Driver ----------

# JS payload: wait for title cards to hydrate, then return their structured
# data. We extract from LI.js-titleCard.Item (each book) and pull title,
# author, format, and the borrow/hold action button text.
_GRAB_JS = r"""
(async function () {
  // Poll up to 15s for title cards to appear
  let cards = [];
  for (let i = 0; i < 30; i++) {
    cards = document.querySelectorAll('li.js-titleCard.Item');
    if (cards.length > 0) break;
    await new Promise(r => setTimeout(r, 500));
  }
  // Look for "no results" message to distinguish empty results from timeout
  const noResults = document.body.innerText.includes('No results found')
    || document.body.innerText.includes('no results');

  const results = Array.from(cards).map(card => {
    // Title + author often inside InfoPanel container
    const infoPanel = card.querySelector('.InfoPanel') || card;
    // Title link is usually the first anchor with a non-button href
    const titleLink = card.querySelector('a[href*="/media/"], .title-name a, h3 a');
    // Borrow/hold button gives availability + format via data attrs
    const actionBtn = card.querySelector('.js-borrow, .js-place-a-hold, [class*=is-borrow], [class*=is-hold]');
    const data = {};
    if (actionBtn) {
      data.media_id = actionBtn.getAttribute('data-media-id') || null;
      data.format = actionBtn.getAttribute('data-type-name')
                    || actionBtn.getAttribute('data-type') || null;
      data.action = (actionBtn.innerText || '').trim();
    }
    // Title text fallback: walk card.innerText to find first non-action chunk
    const allText = card.innerText.trim();
    const lines = allText.split('\n').map(s => s.trim()).filter(Boolean);
    // Drop trailing action words
    const cleaned = lines.filter(l => !/^(BORROW|PLACE A HOLD|AUDIOBOOK|EBOOK|VIDEO|MAGAZINE|VIEW DETAILS)$/i.test(l));
    return {
      title: cleaned[0] || null,
      // OverDrive often formats as "Title\nby Author" -- pull the by line
      author: (cleaned.find(l => l.toLowerCase().startsWith('by ')) || '').replace(/^by\s+/i, '') || null,
      media_id: data.media_id,
      format: data.format,
      action: data.action || null,
      // Wait list count, if shown
      wait_info: (allText.match(/(?:Wait list|Wait time)[:\s]*[^\n]{1,60}/i) || [null])[0],
    };
  });
  return JSON.stringify({
    href: location.href,
    title: document.title,
    n_results: results.length,
    no_results_banner: noResults,
    results,
  });
})()
"""


async def search(library: str, query: str, *, cdp_host: str = "127.0.0.1",
                 cdp_port: int = 9222, nav_wait: float = 5.0) -> dict:
    """Search a library OverDrive instance for a title query.

    library: subdomain key (e.g. 'nypl', 'sfpl', 'bpl'). The full URL is
        ``https://<library>.overdrive.com``.
    query: free-text search query.
    """
    q = urllib.parse.quote(query)
    url = f"https://{library}.overdrive.com/search?query={q}"
    pages = _list_pages(cdp_host, cdp_port)
    page = _pick_page(pages, library)
    ws_url = _ws_url(page, cdp_host, cdp_port)
    async with websockets.connect(ws_url, max_size=32 * 1024 * 1024) as ws:
        await _cdp_send(ws, 1, "Page.enable")
        await _cdp_send(ws, 2, "Page.navigate", {"url": url})
        await asyncio.sleep(nav_wait)
        r = await _cdp_send(ws, 3, "Runtime.evaluate",
                            {"expression": _GRAB_JS, "returnByValue": True,
                             "awaitPromise": True, "timeout": 25000})
        v = r.get("result", {}).get("result", {})
        if v.get("type") != "string":
            raise RuntimeError(f"eval failed: {r}")
        return json.loads(v["value"])


# ---------- CLI ----------

def main() -> int:
    p = argparse.ArgumentParser(
        prog="library-overdrive",
        description=(
            "Search a library's OverDrive catalog and report availability. "
            "Requires Chrome with --remote-debugging-port=9222."
        ),
    )
    p.add_argument("--library", required=True,
                   help="library OverDrive subdomain (e.g. 'nypl', 'sfpl', 'bpl')")
    p.add_argument("--query", required=True, help="title or author search")
    p.add_argument("--cdp-host", default="127.0.0.1")
    p.add_argument("--cdp-port", type=int, default=9222)
    p.add_argument("--nav-wait", type=float, default=5.0)
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument("--available-only", action="store_true",
                   help="only list titles available for immediate borrow")
    args = p.parse_args()

    result = asyncio.run(search(
        args.library, args.query,
        cdp_host=args.cdp_host, cdp_port=args.cdp_port,
        nav_wait=args.nav_wait,
    ))

    rows = result.get("results", [])
    if args.available_only:
        rows = [r for r in rows if (r.get("action") or "").upper() == "BORROW"]

    if args.format == "json":
        json.dump({
            "library": args.library,
            "query": args.query,
            "url": result.get("href"),
            "n_results": len(rows),
            "no_results_banner": result.get("no_results_banner"),
            "results": rows,
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    # text format
    print(f"Library OverDrive search -- {args.library}: \"{args.query}\"")
    print(f"  source: {result.get('href')}")
    print(f"  {len(rows)} result(s) shown"
          + (f" (filtered to BORROW only from {result.get('n_results',0)})"
             if args.available_only else ""))
    if result.get("no_results_banner"):
        print("  (catalog returned 'no results')")
    print()
    if not rows:
        return 1
    for r in rows:
        action_icon = {
            "BORROW": "[available]",
            "PLACE A HOLD": "[on hold]",
        }.get((r.get("action") or "").upper(), f"[{r.get('action') or '?'}]")
        title = r.get("title") or "(untitled)"
        author = r.get("author") or ""
        fmt = r.get("format") or "?"
        wait = r.get("wait_info") or ""
        line = f"  {action_icon:<14} {title}"
        if author:
            line += f" -- {author}"
        line += f"  ({fmt})"
        if wait:
            line += f"  [{wait.strip()}]"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
