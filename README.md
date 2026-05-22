# unbillicord

A Python library for driving and observing a live browser session from Python
code, with bidirectional async event flow. Python pushes JavaScript into the
page; the page emits events back.

## Two transports

1. **JS-injection mode** (working today, lifted from snapp) — a one-time
   paste-bootstrap opens a WebSocket from the page back to the Python server.
   Site-agnostic, no Chrome flags, but bootstrap is manual and injection
   dies on navigation unless re-pasted.

2. **CDP sidecar mode** (planned — see [HANDOFF.md](HANDOFF.md)) — a Python
   sidecar speaks Chrome DevTools Protocol to a CDP-enabled browser. Gives
   nav-surviving injection (`Page.addScriptToEvaluateOnNewDocument`) and
   CAPTCHA-safe trusted-event dispatch (`Input.dispatchKeyEvent`). Requires
   the browser launched with `--remote-debugging-port`.

Same `executor.exec / on / add_init / navigate` API across both transports.

## Use cases

- Authenticated API automation (call APIs in browser context with session cookies)
- Scrape orchestration with DOM-event triggers
- Download monitoring (watch DOM for ready-links, hand off filenames to Python)
- Form automation
- Interactive Python-REPL → browser debugging

## Status

- `src/unbillicord/` — JS-injection implementation, copied from
  `snapp/src/unbillicord/` on 2026-05-22. Light cleanup pending. Site-agnostic
  API surface; the snapp-specific defaults (port 18199, gigaro.ai client URL,
  `tau` cert SAN) are stripped — `data/unbillicord/config.json` ships with
  localhost defaults.
- `src/unbillicord/README.md` — the API documentation (server/client/browser).
  Still uses snapp examples in places; treat as authoritative for the API,
  illustrative for the use cases.
- `src/unbillicord/EVENTS.md` — event-system documentation.
- `src/unbillicord/NGINX.md` — deployment notes for fronting the executor with
  nginx (TLS termination, path-based routing).
- CDP sidecar — not yet built. Next-agent task; see HANDOFF.md.

## Layout

```
executor/
├── README.md              this file
├── HANDOFF.md             design doc for the next agent picking this up
├── .gitignore
├── .local/                gitignored — local dev notes, gitea config
├── src/unbillicord/          library source (snapp base + planned CDP sidecar)
│   ├── __init__.py
│   ├── server.py          WS server (1039 LOC — handles both /remote browser and /client python endpoints)
│   ├── client.py          Python client (473 LOC)
│   ├── common.py          shared config loader
│   ├── config.py          config schema
│   ├── htdocs/            served static files: remote.js (the bootstrap),
│   │                       evtcap.js (console tap helper), install-cert scripts
│   ├── scripts/           cert install helpers
│   ├── README.md          API reference (snapp-flavored examples)
│   ├── EVENTS.md          event system
│   └── NGINX.md           nginx deployment notes
├── data/unbillicord/
│   └── config.json        template — localhost defaults, no TLS
└── tests/
    └── test_executor.py   smoke test carried from snapp
```

## Configuration

Set `PRJ_DIR` to the project root before running:

```bash
export PRJ_DIR=/d/pm/mounts/global/prj/dev/unbillicord
```

(There's a `.init` convention in sibling projects — port that pattern if you
want a sourceable env file. Not done yet.)

Then edit `$PRJ_DIR/data/unbillicord/config.json` for your transport:

```json
{
  "verbose": false,
  "log_file": "log/executor.log",
  "server_url": "http://127.0.0.1:7773",
  "client_url": "http://127.0.0.1:7773",
  "cert_sans": null
}
```

For TLS: set `cert_sans` to a comma-separated list of hostnames/IPs to
include in the cert SANs (e.g. `"localhost,192.168.1.100"`) and use an
`https://` scheme on `server_url`. Cert install helpers under
`src/unbillicord/scripts/`.

## Quick start (current JS-injection mode)

```bash
cd $PRJ_DIR
PYTHONPATH=src python -m executor.server
```

Then in the browser DevTools console of the target page:

```javascript
fetch('http://127.0.0.1:7773/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);
```

Then from Python:

```python
import asyncio
from unbillicord import ExecutorClient

async def main():
    async with ExecutorClient() as client:
        title = await client.exec('document.title')
        print(title)

asyncio.run(main())
```

See `src/unbillicord/README.md` for the full API.
