# loominum

A Python library for driving and observing a live browser session from Python
code, with bidirectional async event flow. Python pushes JavaScript into the
page; the page emits events back.

## Two transports

1. **JS-injection mode** (working today) — a one-time paste-bootstrap opens a
   WebSocket from the page back to the Python server. Site-agnostic, no Chrome
   flags, but bootstrap is manual and injection dies on navigation unless
   re-pasted.

2. **CDP sidecar mode** (working today, via the `lum-cdp` console script) —
   a Python sidecar speaks Chrome DevTools Protocol to a CDP-enabled browser
   and impersonates a browser to the Loominum server. Gives nav-surviving
   injection (`Page.addScriptToEvaluateOnNewDocument`) and CAPTCHA-safe
   trusted-event dispatch (`Input.dispatchKeyEvent` / `dispatchMouseEvent`).
   Requires the browser launched with `--remote-debugging-port`.

Same `lum.exec / on / add_init / navigate` API across both transports.

## Use cases

- Authenticated API automation (call APIs in browser context with session cookies)
- Scrape orchestration with DOM-event triggers
- Download monitoring (watch DOM for ready-links, hand off filenames to Python)
- Form automation
- Interactive Python-REPL → browser debugging

## Status

- `src/loominum/` — JS-injection implementation. Site-agnostic API surface;
  ships with localhost defaults in `data/loominum/config.json` (port 7773,
  TLS off).
- `src/loominum/README.md` — the API documentation (server/client/browser).
- `src/loominum/EVENTS.md` — event-system documentation.
- `src/loominum/NGINX.md` — deployment notes for fronting the server with
  nginx (TLS termination, path-based routing).
- CDP sidecar — implemented in `src/loominum/cdp.py`; run via the
  `lum-cdp` console script. Bridge logic covered by an automated fake-CDP
  test harness in `tests/test_cdp.py`.

## Layout

```
loominum/
├── README.md              this file
├── HANDOFF.md             design doc for the next agent picking this up
├── src/loominum/        library source (JS-injection base + planned CDP sidecar)
│   ├── __init__.py
│   ├── server.py          WS server — handles both the /remote browser and /client python endpoints
│   ├── client.py          Python client
│   ├── common.py          shared config loader
│   ├── config.py          config schema
│   ├── htdocs/            served static files: remote.js (the bootstrap),
│   │                       evtcap.js (console tap helper), install-cert scripts
│   ├── scripts/           cert install helpers
│   ├── README.md          API reference
│   ├── EVENTS.md          event system
│   └── NGINX.md           nginx deployment notes
├── data/loominum/
│   └── config.json        template — localhost defaults, no TLS
└── tests/
    └── test_lum.py        smoke test
```

## Configuration

Set `PRJ_DIR` to the project root before running:

```bash
export PRJ_DIR=/path/to/loominum
```

Then edit `$PRJ_DIR/data/loominum/config.json` for your transport:

```json
{
  "verbose": false,
  "log_file": "log/lum.log",
  "server_url": "http://127.0.0.1:7773",
  "client_url": "http://127.0.0.1:7773",
  "cert_sans": null
}
```

For TLS: set `cert_sans` to a comma-separated list of hostnames/IPs to
include in the cert SANs (e.g. `"localhost,192.168.1.100"`) and use an
`https://` scheme on `server_url`. Cert install helpers under
`src/loominum/scripts/`.

## Quick start (current JS-injection mode)

```bash
cd $PRJ_DIR
PYTHONPATH=src python -m loominum.server
```

Then in the browser DevTools console of the target page:

```javascript
fetch('http://127.0.0.1:7773/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);
```

Then from Python:

```python
import asyncio
from loominum import LumClient

async def main():
    async with LumClient() as client:
        title = await client.exec('document.title')
        print(title)

asyncio.run(main())
```

See `src/loominum/README.md` for the full API.

## Quick start (CDP sidecar mode)

Launch a Chromium-based browser with remote debugging enabled:

```bash
chromium --remote-debugging-port=9222
```

Then start the server and the sidecar (it discovers the target tab,
auto-injects the page bridge, and impersonates a browser to the server):

```bash
cd $PRJ_DIR
PYTHONPATH=src python -m loominum.server &
lum-cdp --target-url example.com
```

From Python, the API is identical to JS-injection mode:

```python
import asyncio
from loominum import LumClient

async def main():
    async with LumClient() as client:
        print(await client.exec('document.title'))

asyncio.run(main())
```

The CDP transport survives page navigations (init code re-runs on every new
document) and can dispatch trusted input via `CDPTransport.dispatch_key`,
`type_text`, and `click`.

## Testing

```bash
pytest tests/test_cdp.py
```

Covers the bridge with a fake CDP browser (no real Chrome required). A real-
browser scenario auto-runs when `localhost:9222` is reachable and otherwise
skips.

## License

Apache-2.0 — see [LICENSE](LICENSE).
