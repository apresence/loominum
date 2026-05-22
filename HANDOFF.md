# unbillicord — handoff for the next agent

Read this first if you're picking this project up.

## What this is

`unbillicord` is being extracted from snapp into a standalone library. The
goal is a publishable Python package that does the heavy lifting of
driving a live browser from Python with bidirectional async events —
across two transports — so application code doesn't have to.

Read `README.md` for the user-facing pitch. This file is the developer-facing
plan.

## Where the code came from

`src/unbillicord/` was copied verbatim from `snapp/src/unbillicord/` on 2026-05-22.
Cleanup so far:

- `data/unbillicord/config.json` — replaced snapp-specific values with
  localhost defaults, TLS off.
- `__pycache__/` removed.
- Cert artefacts (`*.pem.bak`) not copied; cert install scripts retained.

Cleanup **not** done yet (low risk, defer until you start touching code):

- `src/unbillicord/README.md` still uses some snapp examples (download-monitor
  patterns, clip IDs). Replace with site-agnostic examples.
- `common.py` requires `$PRJ_DIR`. Fine for `snapp`'s monorepo style, awkward
  for a library. Consider supporting an explicit config path or a normal
  config-discovery (cwd, `~/.config/executor/`, env).
- `config.py` raises if `data/unbillicord/config.json` is missing. A library
  should ship sensible defaults and only require config for non-default
  setups.

## Architecture — current (JS injection)

```
Browser tab                         Python host
┌──────────────┐                   ┌────────────────────┐
│  Page        │                   │  RemoteExecutor    │
│   ⇣          │   /remote (WSS)   │    (server.py)     │
│  remote.js   ◄═══════════════════►                    │
│   ⇡ emit()   │                   │     ⇣              │
│              │                   │   _dispatch_event  │
└──────────────┘                   │     ⇡              │
                                   │   /client (WSS)    │
                                   │     ⇣              │
                                   │  ExecutorClient ◄──┼─ your code
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
│  RemoteExecutor    │  ← unchanged
│  ExecutorClient    │  ← unchanged
└────────────────────┘
```

Key idea: the sidecar **impersonates a connected browser** to the existing
server. From the server's perspective nothing changes. The sidecar:

1. Discovers the target tab via `GET http://localhost:9222/json` (filter
   by URL substring).
2. Opens a CDP WebSocket to the tab's `webSocketDebuggerUrl`.
3. Registers a CDP binding (e.g. `executorSend`) that the page can call —
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
executor.add_init(js: str)
executor.on(event: str, handler: Awaitable)
executor.off(event: str, handler=None)
executor.exec(code: str, timeout: float = 30.0) -> Any
executor.navigate(url: str)
executor.is_connected() -> bool
executor.reset()
```

**Client side (Python, talking to a remote server over /client WSS):**

```python
ExecutorClient(url=None)
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

1. **Phase 0** — light cleanup pass on what's here. Remove snapp examples
   from `src/unbillicord/README.md`, decouple config from `$PRJ_DIR` (allow
   explicit path or stdlib `appdirs`-style default). Smoke-test the
   carried-over `tests/test_executor.py`.

2. **Phase 1** — package skeleton. Add `pyproject.toml`, console-script
   entrypoint (`unbillicord` → `executor.server:main`), pin runtime deps
   (`aiohttp` etc.).

3. **Phase 2** — CDP sidecar. New module, e.g. `src/unbillicord/cdp.py`:
   `class CDPTransport` with `start(target_url, page_script)`,
   `evaluate(js)`, `dispatch_key(...)`. Wire as an alternate front-end to
   `RemoteExecutor` — sidecar opens an outbound WSS to the existing
   `/remote` endpoint, presenting itself as a normal browser.

4. **Phase 3** — docs, examples, release. README rewrite around the two
   transports as first-class concepts. Examples for each.

## Out of scope (deliberately)

- Webbie's `page.js` — claude.ai-specific DOM glue, throwaway.
- Webbie-MCP multi-tenant OAuth gateway — orthogonal concern. Don't pull
  it in unless explicitly asked.
- Anything site-specific. The library stays a primitive; applications
  build on top.

## Open questions to flag to Chris

- Package name on PyPI (`unbillicord` is taken; bikeshed later).
- License (MIT? Apache-2.0?).
- Whether to support a `.init`-style sourceable env file like sibling
  projects, or a more conventional config-discovery.
- Snapp will keep its own embedded copy until the library is published —
  do not delete `snapp/src/unbillicord/` without his sign-off.

## Pointers

- snapp executor source (the parent): `/d/pm/mounts/global/prj/dev/snapp/src/unbillicord/`
- snapp-specific session memory:
  `~/.claude/projects/C--Users-apres/memory/history/session_20260329_snapp_executor.md`
- webbie CDP reference: `gigaro/cortex-docs` repo, `mvp-2/cortex-ex/services/webbie/relay.js`
  (Node, useful for CDP patterns; do NOT copy page.js).
- Multi-tenant OAuth (out of scope but worth knowing about):
  `gigaro/cortex-docs`, `webbie-mcp/multi-tenant-gateway-spec.md`.
