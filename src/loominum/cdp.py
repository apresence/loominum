"""
Loominum CDP sidecar transport.

Bridges a CDP-enabled browser to a running Loominum server. The sidecar
speaks the Chrome DevTools Protocol to the browser and, separately, opens a
WebSocket to the server's /remote endpoint — impersonating a normal browser.

From the server's and the LumClient's point of view nothing changes. But the
page bridge is now injected over CDP (so it survives navigation via
Page.addScriptToEvaluateOnNewDocument), and input can be dispatched as trusted
events (Input.dispatchKeyEvent / Input.dispatchMouseEvent).

Requires the target browser launched with --remote-debugging-port, e.g.:

    chromium --remote-debugging-port=9222

Run the sidecar against a running server with:

    lum-cdp --target-url example.com
"""

import sys
import json
import asyncio
import logging
import argparse
import itertools
import typing as tp
from urllib.parse import urlparse

import aiohttp
import websockets

logger = logging.getLogger(__name__)

DEFAULT_DEBUG_URL = "http://localhost:9222"
BINDING_NAME = "lumSend"


def page_script(binding_name: str = BINDING_NAME) -> str:
    """JS injected into every document over CDP.

    Provides ``window._remote`` — the same browser-side API as the
    JS-injection transport — but backed by a CDP binding instead of a
    WebSocket. The sidecar drives exec/init directly via Runtime.evaluate,
    so this shim only has to cover page-initiated ``emit`` and the
    cleanup-tracking helpers.
    """
    return _PAGE_SCRIPT_TEMPLATE.replace("__BINDING__", binding_name)


_PAGE_SCRIPT_TEMPLATE = r"""
(function () {
  if (window._remote && window._remote.__cdp) return;
  var state = { observers: [], intervals: [], timeouts: [], listeners: [], cleanup: [] };
  function cleanup() {
    state.observers.forEach(function (o) { try { o.disconnect(); } catch (e) {} });
    state.intervals.forEach(function (i) { clearInterval(i); });
    state.timeouts.forEach(function (t) { clearTimeout(t); });
    state.listeners.forEach(function (l) {
      try { l.element.removeEventListener(l.event, l.handler); } catch (e) {}
    });
    state.cleanup.forEach(function (fn) { try { fn(); } catch (e) {} });
    state.observers = []; state.intervals = []; state.timeouts = [];
    state.listeners = []; state.cleanup = [];
  }
  window._remote = {
    __cdp: true,
    emit: function (eventType, data) {
      try {
        window.__BINDING__(JSON.stringify({
          type: "event", eventType: eventType, data: data || {}
        }));
        return true;
      } catch (e) { return false; }
    },
    addObserver: function (o) { state.observers.push(o); return o; },
    addInterval: function (i) { state.intervals.push(i); return i; },
    addTimeout: function (t) { state.timeouts.push(t); return t; },
    addListener: function (el, ev, fn) {
      el.addEventListener(ev, fn);
      state.listeners.push({ element: el, event: ev, handler: fn });
      return fn;
    },
    addCleanup: function (fn) { state.cleanup.push(fn); },
    cleanup: cleanup
  };
})();
""".strip()


class CDPError(Exception):
    """A CDP command returned an error, or the protocol exchange failed."""


def _rebase_ws_url(ws_url: str, debug_url: str) -> str:
    """Rewrite a webSocketDebuggerUrl's host:port to match ``debug_url``.

    Chrome reports the debugger URL with whatever host it thinks it has,
    which is often ``localhost`` even when reached another way.
    """
    return urlparse(ws_url)._replace(netloc=urlparse(debug_url).netloc).geturl()


async def find_target(debug_url: str = DEFAULT_DEBUG_URL,
                      url_substring: tp.Optional[str] = None) -> dict:
    """Query the browser's /json endpoint and return a matching page target.

    Args:
        debug_url: base URL of the remote-debugging endpoint.
        url_substring: if given, only match a tab whose URL contains it.

    Returns:
        The target dict (includes 'webSocketDebuggerUrl').

    Raises:
        CDPError: if no matching page target is found.
    """
    list_url = debug_url.rstrip("/") + "/json"
    async with aiohttp.ClientSession() as session:
        async with session.get(list_url) as resp:
            resp.raise_for_status()
            targets = await resp.json(content_type=None)

    pages = [t for t in targets
             if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if url_substring:
        pages = [t for t in pages if url_substring in (t.get("url") or "")]
    if not pages:
        where = f" with URL containing {url_substring!r}" if url_substring else ""
        raise CDPError(f"No page target at {debug_url}{where}")
    return pages[0]


class CDPClient:
    """Minimal Chrome DevTools Protocol client over a WebSocket.

    Speaks the CDP JSON-RPC dialect: numbered commands awaited by id, plus
    fire-and-forget events dispatched to registered handlers.
    """

    def __init__(self, ws_debugger_url: str):
        self.ws_url = ws_debugger_url
        self._ws: tp.Optional[tp.Any] = None
        self._ids = itertools.count(1)
        self._pending: tp.Dict[int, asyncio.Future] = {}
        self._handlers: tp.Dict[str, tp.List[tp.Callable]] = {}
        self._recv_task: tp.Optional[asyncio.Task] = None

    async def connect(self) -> None:
        self._ws = await websockets.connect(self.ws_url, max_size=None)
        self._recv_task = asyncio.create_task(self._recv_loop())
        logger.info("CDP connected: %s", self.ws_url)

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws is not None:
            await self._ws.close()

    def on(self, event: str, handler: tp.Callable) -> None:
        """Register a handler for a CDP event (e.g. 'Runtime.bindingCalled').

        The handler receives the event 'params' dict and may be sync or async.
        """
        self._handlers.setdefault(event, []).append(handler)

    async def call(self, method: str, **params: tp.Any) -> dict:
        """Send a CDP command and await its result.

        Raises:
            CDPError: if not connected or the command returns an error.
        """
        if self._ws is None:
            raise CDPError("CDP not connected")
        msg_id = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        await self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        return await fut

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut is not None and not fut.done():
                        if "error" in msg:
                            fut.set_exception(CDPError(str(msg["error"])))
                        else:
                            fut.set_result(msg.get("result", {}))
                elif "method" in msg:
                    for handler in self._handlers.get(msg["method"], []):
                        try:
                            result = handler(msg.get("params", {}))
                            if asyncio.iscoroutine(result):
                                asyncio.create_task(result)
                        except Exception:
                            logger.exception("CDP event handler failed: %s", msg["method"])
        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            pass
        except Exception:
            logger.exception("CDP receive loop crashed")
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(CDPError("CDP connection closed"))
            self._pending.clear()


def _ws_remote_url(server_url: str) -> str:
    """Turn an http(s) server URL into its ws(s) /remote endpoint."""
    parsed = urlparse(server_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/") + "/remote"
    return f"{scheme}://{parsed.netloc}{path}"


def _wrap_exec(code: str) -> str:
    """Wrap Loominum exec/init code (a function body that may ``return``)
    into an awaitable IIFE — mirrors remote.js's safeExec."""
    return "(async () => {" + code + "\n})()"


def _format_exception(exc: dict) -> str:
    """Render a CDP exceptionDetails object into a readable message."""
    obj = exc.get("exception") or {}
    return (obj.get("description")
            or obj.get("value")
            or exc.get("text")
            or "evaluation error")


class CDPTransport:
    """CDP sidecar — bridges a browser (over CDP) to an Loominum server.

    The sidecar connects to the browser's DevTools endpoint and, separately,
    to the server's /remote WebSocket. It relays:

      - page  -> server : window._remote.emit(...) -> CDP binding -> /remote
      - server -> page  : exec/init -> Runtime.evaluate; navigate -> Page.navigate

    Usage:
        t = CDPTransport("http://127.0.0.1:7773", target_url="example.com")
        await t.start()
        await t.run_forever()
    """

    def __init__(self, server_url: str, *,
                 debug_url: str = DEFAULT_DEBUG_URL,
                 target_url: tp.Optional[str] = None,
                 binding_name: str = BINDING_NAME,
                 verify_ssl: bool = True):
        self.server_url = server_url
        self.debug_url = debug_url
        self.target_url = target_url
        self.binding_name = binding_name
        self.verify_ssl = verify_ssl
        self.cdp: tp.Optional[CDPClient] = None
        self._server_ws: tp.Optional[tp.Any] = None
        self._init_script_id: tp.Optional[str] = None

    async def start(self) -> None:
        """Discover the tab, attach over CDP, and connect to the server."""
        # 1. discover the tab and open the CDP connection
        target = await find_target(self.debug_url, self.target_url)
        logger.info("CDP target: %s", target.get("url"))
        self.cdp = CDPClient(_rebase_ws_url(target["webSocketDebuggerUrl"], self.debug_url))
        await self.cdp.connect()

        # 2. enable the domains we need
        await self.cdp.call("Page.enable")
        await self.cdp.call("Runtime.enable")

        # 3. binding for page -> sidecar messages
        self.cdp.on("Runtime.bindingCalled", self._on_binding_called)
        await self.cdp.call("Runtime.addBinding", name=self.binding_name)

        # 4. inject the page bridge — on every future document, and right now
        source = page_script(self.binding_name)
        await self.cdp.call("Page.addScriptToEvaluateOnNewDocument", source=source)
        await self.cdp.call("Runtime.evaluate", expression=source)

        # 5. connect to the Loominum server, impersonating a browser
        ws_url = _ws_remote_url(self.server_url)
        ssl_arg = None
        if ws_url.startswith("wss://") and not self.verify_ssl:
            import ssl as _ssl
            ssl_arg = _ssl.create_default_context()
            ssl_arg.check_hostname = False
            ssl_arg.verify_mode = _ssl.CERT_NONE
        self._server_ws = await websockets.connect(ws_url, ssl=ssl_arg, max_size=None)
        logger.info("connected to Loominum server: %s", ws_url)

        # 6. announce ourselves — prompts the server to replay init code
        url = await self.evaluate("return location.href")
        await self._server_send({"type": "ready", "url": url})

    async def run_forever(self) -> None:
        """Relay server -> page messages until the server connection closes."""
        if self._server_ws is None:
            raise CDPError("call start() before run_forever()")
        try:
            async for raw in self._server_ws:
                await self._handle_server_message(json.loads(raw))
        except websockets.exceptions.ConnectionClosed:
            logger.info("Loominum server connection closed")

    # --- server -> page --------------------------------------------------

    async def _handle_server_message(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "exec":
            await self._handle_exec(msg)
        elif mtype == "init":
            await self._handle_init(msg.get("code", ""))
        elif mtype == "navigate":
            await self.navigate(msg["url"])
        elif mtype == "pong":
            pass
        else:
            logger.debug("ignoring server message type: %s", mtype)

    async def _handle_exec(self, msg: dict) -> None:
        call_id = msg.get("id")
        try:
            result = await self.evaluate(msg.get("code", ""))
            await self._server_send({"type": "result", "id": call_id,
                                     "success": True, "result": result})
        except Exception as e:
            await self._server_send({"type": "result", "id": call_id,
                                     "success": False, "error": str(e)})

    async def _handle_init(self, code: str) -> None:
        if not code:
            return
        assert self.cdp is not None
        # re-inject on every future navigation (replace any previous block)
        if self._init_script_id is not None:
            await self.cdp.call("Page.removeScriptToEvaluateOnNewDocument",
                                identifier=self._init_script_id)
        res = await self.cdp.call("Page.addScriptToEvaluateOnNewDocument",
                                  source=_wrap_exec(code))
        self._init_script_id = res.get("identifier")
        # and run it once for the current document
        await self.evaluate(code)

    # --- page -> server --------------------------------------------------

    async def _on_binding_called(self, params: dict) -> None:
        if params.get("name") != self.binding_name:
            return
        # the page passed a ready-made {type:'event', ...} JSON string
        payload = params.get("payload", "")
        if self._server_ws is not None and payload:
            await self._server_ws.send(payload)

    # --- CDP actions -----------------------------------------------------

    async def evaluate(self, code: str, *, await_promise: bool = True) -> tp.Any:
        """Evaluate Loominum exec-style code (a function body) in the page.

        Raises:
            CDPError: if the page code throws.
        """
        if self.cdp is None:
            raise CDPError("not started")
        resp = await self.cdp.call(
            "Runtime.evaluate",
            expression=_wrap_exec(code),
            returnByValue=True,
            awaitPromise=await_promise,
        )
        exc = resp.get("exceptionDetails")
        if exc:
            raise CDPError(_format_exception(exc))
        return resp.get("result", {}).get("value")

    async def navigate(self, url: str) -> None:
        """Navigate the page (Page.navigate)."""
        if self.cdp is None:
            raise CDPError("not started")
        await self.cdp.call("Page.navigate", url=url)

    async def dispatch_key(self, key: str, *, code: tp.Optional[str] = None,
                           text: tp.Optional[str] = None) -> None:
        """Dispatch a trusted key press (keyDown then keyUp)."""
        if self.cdp is None:
            raise CDPError("not started")
        common: tp.Dict[str, tp.Any] = {"key": key}
        if code:
            common["code"] = code
        down = dict(common, type="keyDown")
        if text:
            down["text"] = text
        await self.cdp.call("Input.dispatchKeyEvent", **down)
        await self.cdp.call("Input.dispatchKeyEvent", **dict(common, type="keyUp"))

    async def type_text(self, text: str) -> None:
        """Insert text as a trusted input event (Input.insertText)."""
        if self.cdp is None:
            raise CDPError("not started")
        await self.cdp.call("Input.insertText", text=text)

    async def click(self, x: float, y: float, *, button: str = "left") -> None:
        """Dispatch a trusted mouse click at viewport coordinates (x, y)."""
        if self.cdp is None:
            raise CDPError("not started")
        for event_type in ("mousePressed", "mouseReleased"):
            await self.cdp.call("Input.dispatchMouseEvent", type=event_type,
                                x=x, y=y, button=button, clickCount=1)

    async def _server_send(self, msg: dict) -> None:
        if self._server_ws is not None:
            await self._server_ws.send(json.dumps(msg))

    async def close(self) -> None:
        """Tear down both connections."""
        if self._server_ws is not None:
            await self._server_ws.close()
        if self.cdp is not None:
            await self.cdp.close()


def _server_url_from_config() -> str:
    """Best-effort: read client_url from the Loominum config."""
    from loominum.config import LumConf
    return LumConf().client_url


def main() -> None:
    """Console-script entrypoint — the ``lum-cdp`` command."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        prog="lum-cdp",
        description="Loominum CDP sidecar — bridge a CDP browser to a server.")
    parser.add_argument("--debug-url", default=DEFAULT_DEBUG_URL,
                        help=f"browser remote-debugging URL (default: {DEFAULT_DEBUG_URL})")
    parser.add_argument("--target-url", default=None,
                        help="only attach to a tab whose URL contains this substring")
    parser.add_argument("--server-url", default=None,
                        help="Loominum server URL (default: client_url from config)")
    parser.add_argument("--no-verify-ssl", action="store_true",
                        help="skip TLS verification when the server is wss://")
    args = parser.parse_args()

    server_url = args.server_url
    if not server_url:
        try:
            server_url = _server_url_from_config()
        except Exception as e:
            parser.error(f"--server-url not given and config is unavailable: {e}")

    transport = CDPTransport(server_url, debug_url=args.debug_url,
                             target_url=args.target_url,
                             verify_ssl=not args.no_verify_ssl)

    async def _run() -> None:
        await transport.start()
        logger.info("sidecar running — Ctrl-C to stop")
        try:
            await transport.run_forever()
        finally:
            await transport.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
