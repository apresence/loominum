# UnBilliCord

Browser automation system with bidirectional event-driven communication.

## Architecture

```
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│   Browser   │◄───────►│   Server    │◄───────►│  Python     │
│  (remote.js)│  WebSocket  (server.py) │  WebSocket  (your code) │
└─────────────┘         └─────────────┘         └─────────────┘
      │                        │                        │
      │ Sends events          │ Dispatches to handlers │
      │ Receives init/exec    │ Stores init code       │
      │                        │ Manages state          │
```

## Components

### 1. Server (server.py)
- HTTP server for static files (htdocs/)
- WebSocket server with two endpoints:
  - `/remote` - Browser connection
  - `/client` - Python client connection
- Manages initialization code and event handlers
- Automatically reinitializes browser on reconnect

### 2. Browser (remote.js)
- Connects to server via WebSocket
- Executes code sent from Python
- Emits events to Python based on DOM/user actions
- Tracks state for cleanup on reconnect

### 3. Client (client.py)
- Python library to connect and send commands
- Executes JavaScript in browser context
- Navigates browser

## Quick Start

### Start Server

```bash
python src/unbillicord/server.py
```

Server runs on `http://localhost:7773` (configurable via `data/unbillicord/config.json`)

### Connect Browser

In browser console or bookmarklet:

```javascript
fetch('http://localhost:7773/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);
```

### Execute Code (Python)

```python
from unbillicord import UBCClient

client = UBCClient()
await client.connect()

# Execute JavaScript
result = await client.exec('document.title')
print(f"Page title: {result}")

# Navigate
await client.navigate('https://example.com')
```

## Event System

See [EVENTS.md](EVENTS.md) for full documentation.

### Register Browser Observers (Python)

```python
from unbillicord.server import ubc

# This code runs in browser on connect/reconnect
ubc.add_init('''
    // Watch for new download links
    const observer = new MutationObserver((mutations) => {
        // ... detect downloads ...
        window._remote.emit('download_ready', {filename: '...'});
    });
    
    observer.observe(document.body, {childList: true, subtree: true});
    window._remote.addObserver(observer);  // Auto-cleanup
''')
```

### Handle Events (Python)

```python
async def on_download_ready(data):
    print(f"Download: {data['filename']}")
    # Process...

ubc.on('download_ready', on_download_ready)
```

### State Persistence

When server restarts:
1. Browser reconnects automatically
2. Server sends all registered init code
3. Browser cleans up old state (observers, listeners, intervals)
4. Handlers are re-registered

This ensures clean state after restarts.

## API

### Server (RemoteUBC)

**Event Handlers:**
```python
ubc.on(event_type: str, handler: Callable)
    # Register event handler (async function)

ubc.off(event_type: str, handler: Callable = None)
    # Remove specific handler or all handlers for event type
    # Returns True if removed, False if not found

ubc.clear_handlers() -> int
    # Clear all event handlers
    # Returns number of event types cleared

ubc.reset() -> tuple[int, int]
    # Clear both handlers and init code
    # Returns (events_cleared, init_blocks_cleared)
```

**Initialization Code:**
```python
ubc.add_init(code: str)
    # Register initialization code for browser

ubc.clear_init() -> int
    # Clear all initialization code
    # Returns number of blocks cleared
```

**Execution:**
```python
await ubc.exec(code: str, timeout: float = 30.0)
    # Execute JavaScript, return result

await ubc.navigate(url: str)
    # Navigate browser to URL

ubc.is_connected() -> bool
    # Check browser connection status
```

### Important: Server Restart Behavior

**What happens when server restarts:**

1. ✅ **Automatically cleared** (no action needed):
   - Browser reconnects within 5 seconds
   - All registered `init_code` is re-sent to browser
   - Browser cleans up old state (observers, listeners, intervals)

2. ⚠️ **Must be re-registered** (in your startup code):
   - Event handlers (`ubc.on()`)
   - Initialization code (`ubc.add_init()`)

**Pattern for restart-safe setup:**
```python
# In your main application startup (e.g., __main__ or setup function)
from unbillicord.server import ubc

# Register init code (clears on restart, must re-register)
ubc.add_init('''
    // Browser-side setup
    window.observeDownloads = function() { ... };
    window.observeDownloads();
''')

# Register handlers (clears on restart, must re-register)
async def on_download(data):
    print(f"Download: {data['filename']}")

ubc.on('download_ready', on_download)
```

**Don't do this** (handlers lost on restart):
```python
# ❌ In a one-off script
ubc.on('event', my_handler)  # Lost when script exits or server restarts
```

**Manual cleanup during development:**
```python
# Remove specific handler
ubc.off('download_ready', my_handler)

# Remove all handlers for event
ubc.off('download_ready')

# Clear everything
ubc.reset()
```

### Browser (window._remote)

```javascript
window._remote.emit(eventType, data)
    // Send event to Python

window._remote.addObserver(observer)
window._remote.addInterval(id)
window._remote.addTimeout(id)
window._remote.addListener(element, event, handler)
window._remote.addCleanup(fn)
    // Register for auto-cleanup on reconnect

window._remote.cleanup()
    // Manually trigger cleanup (testing/debug)
```

### Client (UBCClient)

```python
client = UBCClient(url=None, db=None)
await client.connect()
await client.close()

# Context manager (preferred)
async with UBCClient() as client:
    result = await client.exec('document.title')
```

**Execution:**
```python
await client.exec(code: str, timeout: float = 30.0)
    # Execute JavaScript, return result

await client.navigate(url: str)
    # Navigate browser to URL
```

**Event Handling (client-side):**
```python
client.on(event_type: str, handler: Callable)
    # Register async event handler for browser-emitted events

client.off(event_type: str, handler: Callable = None)
    # Remove specific handler, or all handlers for event type

# Example: listen for clips_ready event from browser JS
async def on_ready(data):
    print(f"Clips ready: {data['clip_ids']}")

client.on('clips_ready', on_ready)
# ... later ...
client.off('clips_ready', on_ready)
```

**Initialization Code (client-side):**
```python
client.add_init(code: str)
    # Register JS that runs on browser connect/reconnect
    # Forwarded to server, persists across browser reconnects

client.enable_console_tap()
    # Inject JS that forwards console.log/warn/error to Python
    # Events emitted as 'console' with {level, args} payload
```

**Event Flow:**
```
Browser JS calls window._remote.emit('event', data)
    → WebSocket → Server _dispatch_event()
    → WebSocket → Client _dispatch_event()
    → Calls matching handlers registered via client.on()
```

## Use Cases

1. **Authenticated API automation** - Execute API calls in browser context with session cookies
2. **Download orchestration** - Monitor downloads, move files after completion
3. **Form automation** - Fill forms, trigger actions based on page state
4. **Live monitoring** - Watch DOM changes, emit events to Python for processing
5. **Interactive debugging** - Execute code in live browser from Python REPL

## Configuration

Edit `data/unbillicord/config.json`:

```json
{
  "verbose": false,
  "log_file": "log/ubc.log",
  "server_url": "http://127.0.0.1:7773",
  "client_url": "http://127.0.0.1:7773",
  "cert_sans": null
}
```

## Examples

- [.copilot/example_browser_events.py](.copilot/example_browser_events.py) - Event monitoring
- See [EVENTS.md](EVENTS.md) for more patterns

## Troubleshooting

**Browser not connecting**
- Check server is running
- Verify `client_connection_url` in config
- Check browser console for errors

**Events not firing**
- Verify handler is registered: `ubc.event_handlers`
- Check init code was sent: look for "initialization" in server logs
- Verify browser state: `window._remote` should exist

**State persists after restart**
- Ensure using `window._remote.add*()` methods
- Check cleanup runs: look for "Cleaned up browser state" in console

**Server restart loses handlers**
- Handler registration (`ubc.on()`) must happen before browser connects
- Put registration in your main application startup, not ad-hoc scripts

## CDP transport (sidecar mode)

The `ubc-cdp` sidecar bridges a CDP-enabled browser to a running UnBilliCord
server. From `ubc` and `UBCClient`'s perspective nothing changes — the server
just sees "a browser" connected on `/remote`. Under the hood the sidecar
relays between Chrome DevTools Protocol on one side and the server's
WebSocket on the other.

### Why use it

- **Survives navigation.** The page bridge is registered via
  `Page.addScriptToEvaluateOnNewDocument`, so it re-injects on every new
  document instead of dying on page nav (as the JS-injection bootstrap does).
- **Trusted input.** `dispatch_key`, `type_text`, and `click` go through
  `Input.*` CDP commands, which produce trusted events — useful for forms,
  CAPTCHA, and anything that distinguishes synthetic from real input.
- **No paste-bootstrap.** Start the sidecar against a tab and you're attached.

### Usage

1. Launch the browser with remote debugging:

   ```bash
   chromium --remote-debugging-port=9222
   ```

2. Start the server (in another shell):

   ```bash
   PYTHONPATH=src python -m unbillicord.server
   ```

3. Start the sidecar against a target tab:

   ```bash
   ubc-cdp --target-url example.com
   ```

   `--target-url` is an optional substring filter (first matching `type=page`
   target wins). Add `--server-url http://host:port` to override the server URL.

4. Use `UBCClient` exactly as in JS-injection mode.

### Python API

```python
from unbillicord import CDPTransport

t = CDPTransport(
    server_url="http://127.0.0.1:7773",
    debug_url="http://localhost:9222",
    target_url="example.com",
)
await t.start()           # discover, attach, connect to server, announce ready
await t.evaluate("return document.title")
await t.dispatch_key("Enter")
await t.type_text("hello")
await t.click(120, 240)
await t.run_forever()     # relay until the server connection closes
```

### Testing the bridge

`tests/test_cdp.py` ships an automated fake-CDP browser and exercises the
full bridge (init injection, exec round-trip, page→client events, navigate)
without needing a real browser:

```bash
pytest tests/test_cdp.py
```

The same file includes `test_real_browser_e2e`, which auto-runs when
`localhost:9222` is reachable and skips otherwise.
