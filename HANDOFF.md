# unbillicord — handoff for the next agent

Read this first if you're picking this project up.

## What this is

`unbillicord` is a standalone Python library. The goal is a publishable Python
package that does the heavy lifting of driving a live browser from Python with
bidirectional async events — across two transports — so application code
doesn't have to.

Read `README.md` for the user-facing pitch. This file is the developer-facing
plan.

## Status

The library is a site-agnostic primitive: the public API surface carries no
site-specific code, and `data/unbillicord/config.json` ships localhost
defaults (port 7773, TLS off). The JS-injection transport works today. The CDP
sidecar transport is not yet built — that's the next big piece (see below).

Still to do before this is comfortable as a library:

- `common.py` requires `$PRJ_DIR`. Awkward for a library — consider supporting
  an explicit config path or conventional config-discovery (cwd,
  `~/.config/unbillicord/`, env).
- `config.py` raises if `data/unbillicord/config.json` is missing. A library
  should ship sensible defaults and only require config for non-default setups.

## Architecture — current (JS injection)

```
Browser tab                         Python host
┌──────────────┐                   ┌────────────────────┐
│  Page        │                   │  RemoteUBC         │
│   ⇣          │   /remote (WSS)   │    (server.py)     │
│  remote.js   ◄═══════════════════►                    │
│   ⇡ emit()   │                   │     ⇣              │
│              │                   │   _dispatch_event  │
└──────────────┘                   │     ⇡              │
                                   │   /client (WSS)    │
                                   │     ⇣              │
                                   │  UBCClient ◄───────┼─ your code
                                   │   (client.py)      │
                                   └────────────────────┘
```

The server holds two WS endpoints. The browser connects to `/remote`; user
code connects to `/client`. The server keeps a registry of init-code blocks
and event handlers; it replays init-code to the browser on every reconnect.

Bootstrap is manual: paste `fetch(URL+'/remote.js?t='+Date.now()).then(r=>r.text()).then(eval)`
in DevTools.

## Architecture — planned (CDP sidecar)

```
Browser (--remote-debugging-port=9222)
    ⇡ CDP
┌────────────────────┐   ⇣ Runtime.evaluate / Runtime.addBinding
│  CDP sidecar (py)  │   ⇣ Page.addScriptToEvaluateOnNewDocument
│                    │   ⇣ Input.dispatchKeyEvent (trusted)
└─────────⇣──────────┘
          │  same WS protocol the page would speak in JS-injection mode
          ⇡
┌────────────────────┐
│  RemoteUBC         │  ← unchanged
│  UBCClient         │  ← unchanged
└────────────────────┘
```

Key idea: the sidecar **impersonates a connected browser** to the existing
server. From the server's perspective nothing changes. The sidecar:

1. Discovers the target tab via `GET http://localhost:9222/json` (filter
   by URL substring).
2. Opens a CDP WebSocket to the tab's `webSocketDebuggerUrl`.
3. Registers a CDP binding (e.g. `ubcSend`) that the page can call —
   payload arrives as `Runtime.bindingCalled`.
4. Injects `remote.js` via `Page.addScriptToEvaluateOnNewDocument` so it
   survives navigation.
5. Translates: page's `_remote.emit(...)` → CDP binding → forward to
   the existing server's `/remote` endpoint.
6. Translates: server's exec/init commands → `Runtime.evaluate` in the
   page context.
7. Optionally: `Input.dispatchKeyEvent` for trusted input (CAPTCHA-safe).

Estimated effort: ~150 LOC. Look at `gigaro/cortex-docs` repo,
`mvp-2/cortex-ex/services/webbie/relay.js` for a working reference
(Node, ~500 LOC including claude.ai-specific glue you do NOT want).
The CDP primitives there — `CDPClient`, `findTarget`, `addBinding`,
`evaluate` — are exactly what you need to port to Python.

## Transport API contract

Both transports must expose the same surface:

**Server side (Python):**

```python
ubc.add_init(js: str)
ubc.on(event: str, handler: Awaitable)
ubc.off(event: str, handler=None)
ubc.exec(code: str, timeout: float = 30.0) -> Any
ubc.navigate(url: str)
ubc.is_connected() -> bool
ubc.reset()
```

**Client side (Python, talking to a remote server over /client WSS):**

```python
UBCClient(url=None)
client.exec / navigate / on / off / add_init / enable_console_tap
```

**Browser side (JS):**

```javascript
window._remote.emit(eventType, data)
window._remote.addObserver(observer)
window._remote.addInterval(id)
window._remote.addTimeout(id)
window._remote.addListener(el, event, handler)
window._remote.addCleanup(fn)
```

If the CDP sidecar honors all of the above, application code is portable
between transports by config change alone.

## Suggested phasing

1. **Phase 0** — light cleanup. The initial naming/cleanup pass is **done**.
   Remaining: decouple config from `$PRJ_DIR` (allow an explicit path or
   stdlib `appdirs`-style default).

2. **Phase 1** — package skeleton. Add `pyproject.toml`, a console-script
   entrypoint (`ubc` → `unbillicord.server:main`), pin runtime deps
   (`aiohttp` etc.).

3. **Phase 2** — CDP sidecar. New module, e.g. `src/unbillicord/cdp.py`:
   `class CDPTransport` with `start(target_url, page_script)`,
   `evaluate(js)`, `dispatch_key(...)`. Wire as an alternate front-end to
   `RemoteUBC` — sidecar opens an outbound WSS to the existing `/remote`
   endpoint, presenting itself as a normal browser.

4. **Phase 3** — docs, examples, release. README rewrite around the two
   transports as first-class concepts. Examples for each.

## Out of scope (deliberately)

- Webbie's `page.js` — claude.ai-specific DOM glue, throwaway.
- Webbie-MCP multi-tenant OAuth gateway — orthogonal concern. Don't pull
  it in unless explicitly asked.
- Anything site-specific. The library stays a primitive; applications
  build on top.

## Open questions to flag to Chris

- PyPI package name. `unbillicord` is currently **available** on PyPI
  (no published package by that name) — claim it or pick another.
- Whether to support a `.init`-style sourceable env file, or a more
  conventional config-discovery.

License is decided: **Apache-2.0** (see `LICENSE`).

## Pointers

- webbie CDP reference: `gigaro/cortex-docs` repo,
  `mvp-2/cortex-ex/services/webbie/relay.js`
  (Node, useful for CDP patterns; do NOT copy page.js).
- Multi-tenant OAuth (out of scope but worth knowing about):
  `gigaro/cortex-docs`, `webbie-mcp/multi-tenant-gateway-spec.md`.
