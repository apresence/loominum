"""
Python client for connecting to remote executor server.
"""

import json
import uuid
import logging
import asyncio
import websockets

import typing as tp
from pathlib import Path
from datetime import datetime

try:
    from .config import ExecutorConfig
except ImportError:
    from unbillicord.config import ExecutorConfig

logger = logging.getLogger(__name__)

_CONSOLE_TAP_JS: str = r"""
(function consoleTap(options) {
  if (window.__consoleTapInstalled) return;
  window.__consoleTapInstalled = true;
  var opts = options || {};
  var forwardTo = opts.forwardTo || null;
  var levels = ["log", "info", "warn", "error", "debug", "trace"];
  var original = Object.create(null);

  var safeRepr = function(v) {
    try {
      if (v instanceof Error)
        return { __type: "Error", name: v.name, message: v.message, stack: v.stack };
      if (typeof Node !== "undefined" && v instanceof Node)
        return { __type: "Node", text: (v.outerHTML || "").slice(0, 200) || v.nodeName };
      if (v === window) return { __type: "Window" };
      if (v === document) return { __type: "Document" };
      return JSON.parse(JSON.stringify(v));
    } catch(e) {
      try { return String(v); } catch(e2) { return "[unserializable]"; }
    }
  };

  var emit = function(payload) {
    if (typeof forwardTo === "function") {
      try { forwardTo(payload); } catch(e) {}
    }
  };

  for (var i = 0; i < levels.length; i++) {
    (function(level) {
      var fn = console[level];
      if (typeof fn !== "function") return;
      original[level] = fn.bind(console);
      console[level] = function() {
        var args = Array.prototype.slice.call(arguments);
        emit({
          level: level,
          ts: Date.now(),
          argsSafe: args.map(safeRepr)
        });
        return original[level].apply(console, args);
      };
    })(levels[i]);
  }

  window.addEventListener("error", function(e) {
    emit({
      level: "error", ts: Date.now(),
      argsSafe: [safeRepr(e.message)],
      source: "window.error",
      filename: e.filename, lineno: e.lineno, colno: e.colno,
      errorSafe: safeRepr(e.error)
    });
  });

  window.addEventListener("unhandledrejection", function(e) {
    emit({
      level: "error", ts: Date.now(),
      argsSafe: ["Unhandled rejection"],
      source: "unhandledrejection",
      reasonSafe: safeRepr(e.reason)
    });
  });
})({
  forwardTo: function(p) { window._remote.emit("console", p); }
});
""".strip()


class ExecutorClient:
    """Client for connecting to remote executor server."""
    
    def __init__(self, url: tp.Optional[str] = None, db: tp.Optional[tp.Any] = None, ssl_verify: bool = True,
                 cert_path: tp.Optional[str] = None, key_path: tp.Optional[str] = None):
        """
        Initialize executor client.
        
        Args:
            url: WebSocket URL to connect to. If None, uses client_url from executor config.
                 Supports formats:
                 - 'https://host/path' (converts to wss://host/path/client)
                 - 'http://host:port/path' (converts to ws://host:port/path/client)
                 - 'ws://host:port' (legacy, appends /client)
            db: Optional ClipDB instance for API call logging
            ssl_verify: If False, disables SSL certificate verification (for self-signed certs)
            cert_path: Path to client certificate PEM file (optional, defaults to config location)
            key_path: Path to client private key PEM file (optional, defaults to config location)
        """
        if url is None:
            config = ExecutorConfig()
            url = config.client_url
            self._cert_path = cert_path or str(Path(config.config_path.parent) / 'cert.pem')
            self._key_path = key_path or str(Path(config.config_path.parent) / 'key.pem')
        else:
            import os
            prj_dir = os.getenv('PRJ_DIR')
            if not prj_dir:
                raise RuntimeError(
                    "PRJ_DIR environment variable not set. "
                    "Please run: . .init"
                )
            self._cert_path = cert_path or str(Path(prj_dir) / 'data/unbillicord/cert.pem')
            self._key_path = key_path or str(Path(prj_dir) / 'data/unbillicord/key.pem')
        
        # Parse and construct WebSocket URL
        if url.startswith('http://') or url.startswith('https://'):
            # Convert http -> ws, https -> wss
            from urllib.parse import urlparse
            parsed = urlparse(url)
            ws_scheme = 'wss' if parsed.scheme == 'https' else 'ws'
            path = parsed.path.rstrip('/') + '/client'
            self.ws_url = f"{ws_scheme}://{parsed.netloc}{path}"
        elif url.startswith('ws://') or url.startswith('wss://'):
            # Already a WebSocket URL, just append /client if needed
            self.ws_url = url.rstrip('/') + '/client'
        else:
            # Legacy format: assume ws://host:port
            self.ws_url = f"ws://{url}/client"
        
        self.ws: tp.Optional[tp.Any] = None
        self.pending_calls: dict = {}
        self.connected = False
        self.ssl_verify = ssl_verify
        
        # API logging
        self.db = db
        
        # Event handlers: event_type -> [handler_funcs]
        self.event_handlers: tp.Dict[str, tp.List[tp.Callable]] = {}

        # 429 safety valve (throttle timing is on the server)
        self.consecutive_429s: int = 0
        self.max_consecutive_429s: int = 5
    
    async def connect(self):
        """Connect to the executor server."""
        try:
            import ssl as sslmod
            ssl_ctx = None
            print(f"Connecting to executor server at {self.ws_url} with SSL verify={self.ssl_verify}...")
            if self.ws_url.startswith('wss://'):
                ssl_ctx = sslmod.create_default_context()
                if not self.ssl_verify:
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = sslmod.CERT_NONE
                # Load client cert/key if present
                if self._cert_path and self._key_path:
                    try:
                        ssl_ctx.load_cert_chain(certfile=self._cert_path, keyfile=self._key_path)
                        print(f"✓ Loaded client cert: {self._cert_path}, key: {self._key_path}")
                    except Exception as cert_exc:
                        print(f"⚠️ Failed to load client cert/key: {cert_exc}")
                # Load CA cert for trust
                try:
                    ssl_ctx.load_verify_locations(cafile=self._cert_path)
                    print(f"✓ Loaded CA cert for trust: {self._cert_path}")
                except Exception as ca_exc:
                    print(f"⚠️ Failed to load CA cert for trust: {ca_exc}")
            self.ws = await websockets.connect(self.ws_url, ssl=ssl_ctx)
            print(f"✓ WebSocket connected to {self.ws_url}")
            #Start message handler
            asyncio.create_task(self._handle_messages())
            # Give the connection a moment to stabilize and verify it's working
            await asyncio.sleep(0.2)
            # Send a ping to verify connection
            await self.ws.ping()
            self.connected = True
        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            raise
    
    async def _handle_messages(self):
        """Handle incoming messages from server."""
        assert self.ws is not None, "WebSocket connection not established"
        try:
            async for message in self.ws:
                data = json.loads(message)
                
                if data['type'] == 'result':
                    call_id = data['id']
                    if call_id in self.pending_calls:
                        future = self.pending_calls[call_id]
                        if data['success']:
                            future.set_result(data.get('result'))
                        else:
                            future.set_exception(Exception(data.get('error', 'Unknown error')))
                        del self.pending_calls[call_id]

                elif data['type'] == 'event':
                    event_type: tp.Optional[str] = data.get('eventType')
                    event_data: dict = data.get('data', {})
                    if event_type:
                        asyncio.create_task(self._dispatch_event(event_type, event_data))
        
        except websockets.exceptions.ConnectionClosed as e:
            print(f"⚠️  WebSocket connection closed: {e}")
            self.connected = False
        except Exception as e:
            print(f"❌ Error in message handler: {e}")
            self.connected = False
    
    async def exec(self, code: str, timeout: float = 30.0) -> tp.Any:
        """
        Execute JavaScript code in browser.
        
        Args:
            code: JavaScript code to execute
            timeout: Timeout in seconds
            
        Returns:
            Result from JavaScript execution
        """
        assert self.ws is not None, "WebSocket connection not established"

        call_id = str(uuid.uuid4())
        future = asyncio.Future()
        self.pending_calls[call_id] = future
        
        await self.ws.send(json.dumps({
            'type': 'exec',
            'id': call_id,
            'code': code,
            'timeout': timeout
        }))
        
        try:
            result = await asyncio.wait_for(future, timeout=timeout + 5)
            return result
        except asyncio.TimeoutError:
            del self.pending_calls[call_id]
            raise Exception(f"Execution timed out after {timeout}s")
    
    async def is_browser_connected(self) -> bool:
        """
        Check if browser extension is connected to executor server.
        
        Returns:
            True if browser is connected, False otherwise
        """
        try:
            # Try a lightweight operation to see if browser responds
            await self.exec("true", timeout=2.0)
            return True
        except Exception as e:
            error_str = str(e)
            if "No browser connected" in error_str or "timed out" in error_str.lower():
                return False
            # Other errors might indicate browser is connected but something else failed
            return True
    
    async def navigate(self, url: str):
        """Navigate browser to URL."""
        assert self.ws is not None, "WebSocket connection not established"
        
        await self.ws.send(json.dumps({
            'type': 'navigate',
            'url': url
        }))
    
    async def api_exec(self, code: str, timeout: float = 30.0) -> tp.Any:
        """
        Execute JS via server's throttled API path.

        The server serializes all API calls through a global lock with adaptive
        delay, preventing multiple clients from defeating the backoff.

        Args:
            code: JavaScript code to execute
            timeout: Timeout in seconds

        Returns:
            Result from JavaScript execution
        """
        assert self.ws is not None, "WebSocket connection not established"

        call_id: str = str(uuid.uuid4())
        future: asyncio.Future = asyncio.Future()
        self.pending_calls[call_id] = future

        await self.ws.send(json.dumps({
            'type': 'api_exec',
            'id': call_id,
            'code': code,
            'timeout': timeout
        }))

        try:
            result: tp.Any = await asyncio.wait_for(future, timeout=timeout + 10)
            return result
        except asyncio.TimeoutError:
            del self.pending_calls[call_id]
            raise Exception(f"API execution timed out after {timeout}s")

    async def api_call(
        self,
        endpoint: str,
        method: str,
        js_code: str,
        clip_id: tp.Optional[str] = None,
        request_body: tp.Optional[str] = None,
        timeout: float = 30.0
    ) -> tp.Dict[str, tp.Any]:
        """
        Execute API call with server-level throttling and logging.

        All Suno API calls should use this instead of exec() directly.
        Throttle timing is enforced by the executor server (shared across
        all connected clients). This method handles logging and 429 safety.

        Args:
            endpoint: API endpoint path (e.g., "/api/feed/v3")
            method: HTTP method (GET, POST, etc.)
            js_code: JavaScript code (must return {success, status, ...})
            clip_id: Related clip ID if applicable
            request_body: JSON request for logging
            timeout: Request timeout

        Returns:
            Result from JavaScript execution
        """
        start_time: datetime = datetime.now()
        try:
            result: tp.Dict[str, tp.Any] = await self.api_exec(js_code, timeout=timeout)
        except Exception as e:
            # Log failure
            duration_ms: int = int((datetime.now() - start_time).total_seconds() * 1000)
            if self.db:
                self.db.log_api_call(
                    endpoint=endpoint,
                    method=method,
                    clip_id=clip_id,
                    request_body=request_body,
                    response_body=None,
                    response_code=None,
                    error=str(e),
                    duration_ms=duration_ms
                )
            raise

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # 429 safety valve -- server handles delay, client counts for hard stop
        response_code: tp.Optional[int] = result.get('status')
        if response_code == 429 or (not result.get('success') and '429' in str(result.get('error', ''))):
            self.consecutive_429s += 1
            logger.warning(
                f"Rate limit (429) - consecutive: {self.consecutive_429s}/{self.max_consecutive_429s}"
            )
            if self.consecutive_429s >= self.max_consecutive_429s:
                raise RuntimeError(
                    f"Too many consecutive 429s ({self.consecutive_429s}). "
                    f"Stopping to avoid account lock."
                )
        else:
            self.consecutive_429s = 0

        # Log the call
        if self.db:
            error: tp.Optional[str] = result.get('error') if not result.get('success') else None
            response_body: tp.Optional[str] = result.get('response_body')
            if response_body is None:
                response_body = json.dumps(result)

            logged_request_body: tp.Optional[str] = result.get('request_body') or request_body

            api_call_id: int = self.db.log_api_call(
                endpoint=endpoint,
                method=method,
                clip_id=clip_id,
                request_body=logged_request_body,
                response_body=response_body,
                response_code=response_code,
                error=error,
                duration_ms=duration_ms
            )

            # Add api_call_id to result for tracking provenance
            result['__api_call_id'] = api_call_id

        return result
    
    def on(self, event_type: str, handler: tp.Callable) -> None:
        """Register an event handler for browser-initiated events."""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)

    def off(self, event_type: str, handler: tp.Optional[tp.Callable] = None) -> bool:
        """
        Unregister event handler(s).

        Args:
            event_type: Type of event
            handler: Specific handler to remove. If None, removes all for this type.

        Returns:
            True if handler(s) were removed
        """
        if event_type not in self.event_handlers:
            return False
        if handler is None:
            del self.event_handlers[event_type]
            return True
        try:
            self.event_handlers[event_type].remove(handler)
            if not self.event_handlers[event_type]:
                del self.event_handlers[event_type]
            return True
        except ValueError:
            return False

    async def _dispatch_event(self, event_type: str, event_data: dict) -> None:
        """Dispatch event to registered handlers."""
        for handler in self.event_handlers.get(event_type, []):
            try:
                result = handler(event_data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Event handler for '{event_type}' failed: {e}")

    async def add_init(self, code: str) -> None:
        """Send initialization code to server (runs in browser on connect/reconnect)."""
        assert self.ws is not None, "WebSocket connection not established"
        await self.ws.send(json.dumps({'type': 'add_init', 'code': code}))

    async def enable_console_tap(self) -> None:
        """
        Install console-log-tap in the browser as init code.

        Intercepts console.log/info/warn/error/debug/trace and forwards
        payloads as 'console' events via window._remote.emit().
        Register a handler with: executor.on('console', my_handler)
        """
        js: str = _CONSOLE_TAP_JS
        await self.add_init(js)
        # Also execute immediately in the current browser session
        await self.exec(js)

    async def close(self):
        """Close connection to server."""
        if self.ws:
            await self.ws.close()
            self.connected = False
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
