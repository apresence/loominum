"""BART real-time departures -- a loominum example driver.

Demonstrates browser-driving a page where a plain HTTP fetch CAN'T get the
data: BART's real-time ETAs are rendered client-side via JS after page load
and aren't in the SSR HTML.

Usage:
    bart-eta --station EMBR
    bart-eta --station 12TH --format json
    bart-eta --list-stations
"""
from __future__ import annotations
import argparse
import asyncio
import json
import re
import sys
import urllib.request

import websockets

# loominum.fetch is an OPTIONAL extra installed via `pip install loominum[fetch]`.
# Imported only when we use it (HTML-to-text rendering). Module degrades to raw
# text output if not installed.
try:
    from loominum.fetch import html_to_text
    _HAVE_FETCH = True
except ImportError:
    _HAVE_FETCH = False


ETA_URL_TEMPLATE = "https://www.bart.gov/schedules/eta/{station}"


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


def _pick_page(pages: list[dict]) -> dict:
    """Prefer a bart.gov tab, then about:blank, then any page tab."""
    for p in pages:
        if p.get("type") == "page" and "bart.gov" in p.get("url", ""):
            return p
    for p in pages:
        if p.get("type") == "page" and p.get("url", "") == "about:blank":
            return p
    for p in pages:
        if p.get("type") == "page":
            return p
    raise RuntimeError("no Chrome page tab available")


def _ws_url(page: dict, host: str, port: int) -> str:
    """Normalize the CDP WS URL to include host:port.

    CDP's reported ``ws://localhost/devtools/...`` URL can drop the port,
    causing ``websockets.connect`` to default to port 80. Rewrite to the
    known host:port.
    """
    raw = page["webSocketDebuggerUrl"]
    return re.sub(r"://(localhost|127\.0\.0\.1)(:\d+)?",
                  f"://{host}:{port}", raw, count=1)


# ---------- Driver ----------

# JS payload: wait for .schedule-platforms to hydrate, then return its HTML.
_GRAB_JS = r"""
(async function () {
  // Poll up to 15s for the schedule-platforms container to appear and
  // contain at least one 'N min' token (the real-time data).
  let container = null;
  for (let i = 0; i < 30; i++) {
    container = document.querySelector('.schedule-platforms');
    if (container && /\d+\s*min/i.test(container.innerText)) break;
    await new Promise(r => setTimeout(r, 500));
  }
  // Service advisory banner (optional context)
  const advisory = document.querySelector('.alert--service, .messages__container')?.innerText || null;
  return JSON.stringify({
    href: location.href,
    title: document.title,
    station_label: document.querySelector('h2')?.innerText?.trim() || null,
    advisory: advisory ? advisory.slice(0, 500) : null,
    platforms_html: container ? container.outerHTML : null,
    platforms_text: container ? container.innerText : null,
  });
})()
"""


async def get_etas(station_code: str, *, cdp_host: str = "127.0.0.1",
                   cdp_port: int = 9222, nav_wait: float = 4.0) -> dict:
    """Fetch real-time departures for one BART station.

    station_code: 4-char BART station code (e.g. 'EMBR' for Embarcadero).
        Use --list-stations to print the full map.
    """
    url = ETA_URL_TEMPLATE.format(station=station_code.upper())
    pages = _list_pages(cdp_host, cdp_port)
    page = _pick_page(pages)
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


# ---------- Parse ----------

# BART platform text format:
#   Platform 1
#   <destination>
#   N min (X car), M min (X car), K min (X car)
#   <destination>
#   ...
#   Platform 2
#   ...

_PLATFORM_RE = re.compile(r"^Platform\s+(\d+)\s*$", re.I)
_MIN_GROUP_RE = re.compile(r"(\d+)\s*min\s*(?:\((\d+)\s*car\))?", re.I)


def parse_platforms(platform_text: str) -> list[dict]:
    """Parse BART platform text into structured departure rows.

    Returns a list of dicts:
        {platform: 1, destination: 'Daly City',
         departures: [{minutes: 8, cars: 6}, ...]}
    """
    if not platform_text:
        return []
    rows = []
    current_platform: int | None = None
    pending_dest: str | None = None
    for raw in platform_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _PLATFORM_RE.match(line)
        if m:
            current_platform = int(m.group(1))
            pending_dest = None
            continue
        # If this line has 'N min' tokens, it's an ETA line for pending_dest
        mins = _MIN_GROUP_RE.findall(line)
        if mins and pending_dest is not None:
            departures = [{"minutes": int(m_), "cars": int(c_) if c_ else None}
                          for (m_, c_) in mins]
            rows.append({
                "platform": current_platform,
                "destination": pending_dest,
                "departures": departures,
            })
            pending_dest = None
        else:
            pending_dest = line
    return rows


# ---------- Station list ----------

STATIONS = {
    "12TH": "12th St. Oakland City Center", "16TH": "16th St. Mission",
    "19TH": "19th St. Oakland", "24TH": "24th St. Mission",
    "ANTC": "Antioch", "ASHB": "Ashby", "BALB": "Balboa Park",
    "BAYF": "Bay Fair", "BERY": "Berryessa/North San Jose",
    "CAST": "Castro Valley", "CIVC": "Civic Center/UN Plaza",
    "COLM": "Colma", "COLS": "Coliseum", "CONC": "Concord",
    "DALY": "Daly City", "DBRK": "Downtown Berkeley", "DELN": "El Cerrito del Norte",
    "DUBL": "Dublin/Pleasanton", "EMBR": "Embarcadero",
    "FRMT": "Fremont", "FTVL": "Fruitvale", "GLEN": "Glen Park",
    "HAYW": "Hayward", "LAFY": "Lafayette", "LAKE": "Lake Merritt",
    "MCAR": "MacArthur", "MLBR": "Millbrae", "MLPT": "Milpitas",
    "MONT": "Montgomery St.", "NBRK": "North Berkeley",
    "NCON": "North Concord/Martinez", "OAKL": "OAK Airport",
    "ORIN": "Orinda", "PCTR": "Pittsburg Center",
    "PHIL": "Pleasant Hill/Contra Costa Centre", "PITT": "Pittsburg/Bay Point",
    "POWL": "Powell St.", "RICH": "Richmond", "ROCK": "Rockridge",
    "SANL": "San Leandro", "SBRN": "San Bruno", "SFIA": "SFO",
    "SHAY": "South Hayward", "SSAN": "South San Francisco",
    "UCTY": "Union City", "WCRK": "Walnut Creek", "WARM": "Warm Springs/South Fremont",
    "WDUB": "West Dublin/Pleasanton", "WOAK": "West Oakland",
}


# ---------- CLI ----------

def main() -> int:
    p = argparse.ArgumentParser(
        prog="bart-eta",
        description=(
            "BART real-time departures via loominum CDP. "
            "Requires Chrome with --remote-debugging-port=9222 running."
        ),
    )
    p.add_argument("--station", help="4-char BART station code (e.g. EMBR)")
    p.add_argument("--list-stations", action="store_true",
                   help="print the station code -> name map and exit")
    p.add_argument("--cdp-host", default="127.0.0.1")
    p.add_argument("--cdp-port", type=int, default=9222)
    p.add_argument("--nav-wait", type=float, default=4.0,
                   help="seconds to wait after Page.navigate (default 4)")
    p.add_argument("--format", choices=["text", "json"], default="text")
    args = p.parse_args()

    if args.list_stations:
        for code, name in sorted(STATIONS.items()):
            print(f"{code:6} {name}")
        return 0

    if not args.station:
        p.error("--station required (or use --list-stations)")

    code = args.station.upper()
    if code not in STATIONS:
        print(f"warning: '{code}' not in known station list; trying anyway",
              file=sys.stderr)

    result = asyncio.run(get_etas(
        code, cdp_host=args.cdp_host, cdp_port=args.cdp_port,
        nav_wait=args.nav_wait,
    ))

    rows = parse_platforms(result.get("platforms_text", "") or "")

    if args.format == "json":
        json.dump({
            "station_code": code,
            "station_label": STATIONS.get(code, code),
            "url": result.get("href"),
            "advisory": result.get("advisory"),
            "departures": rows,
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    # text format
    print(f"BART real-time departures -- {STATIONS.get(code, code)} ({code})")
    print(f"  source: {result.get('href')}")
    if result.get("advisory"):
        print(f"  advisory: {result['advisory'][:120].strip()}")
    print()
    if not rows:
        print("  (no departures found -- station may have ended service)")
        return 1
    current_p = None
    for row in rows:
        if row["platform"] != current_p:
            current_p = row["platform"]
            print(f"  Platform {current_p}:")
        deps = ", ".join(
            f"{d['minutes']} min" + (f" ({d['cars']}c)" if d["cars"] else "")
            for d in row["departures"]
        )
        print(f"    {row['destination']:<28} {deps}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
