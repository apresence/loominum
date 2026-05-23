#!/usr/bin/env python3
"""
Automated test harness for the Loominum CDP sidecar transport.

Covers:
  - pure-unit helpers (URL / exec-wrapping, page-script templating)
  - find_target against a fake CDP /json endpoint
  - a full e2e of the bridge: a real Loominum server + a real CDPTransport
    + a real LumClient, with a *fake CDP browser* standing in for Chrome.
    Exercises exec round-trip, page->client events, init injection, navigate.
  - an e2e against a *real* browser on localhost:9222, auto-skipped when no
    such browser is reachable.

Run:  pytest tests/test_cdp.py        — or —        python tests/test_cdp.py
"""

import os
import sys
import json
import socket
import asyncio
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("PRJ_DIR", str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

import aiohttp
from aiohttp import web

from loominum.cdp import (
    CDPTransport, CDPError, find_target, page_script,
    _ws_remote_url, _wrap_exec,
)

REAL_CDP_URL = "http://localhost:9222"


# --------------------------------------------------------------------------
# fake CDP browser — a stand-in for Chrome's remote-debugging endpoint
# --------------------------------------------------------------------------

class FakeCDPBrowser:
    """Serves /json (target discovery) and a CDP WebSocket answering the
    handful of commands the sidecar issues. Runtime.evaluate returns a
    programmable canned value, so a test can assert round-trip plumbing
    without a real JS engine.
    """

    def __init__(self, port, page_url="http://example.test/"):
        self.port = port
        self.page_url = page_url
        self.eval_result: Any = None  # what Runtime.evaluate returns
        self.received = []           # [(method, params), ...]
        self._app = web.Application()
        self._app.router.add_get("/json", self._json)
        self._app.router.add_get("/devtools/page/1", self._cdp_ws)
        self._runner = None
        self._ws = None
        self._script_n = 0

    async def start(self):
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", self.port).start()

    async def stop(self):
        if self._runner is not None:
            await self._runner.cleanup()

    async def _json(self, request):
        return web.json_response([{
            "type": "page", "id": "1", "title": "fake",
            "url": self.page_url,
            "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/page/1",
        }])

    async def _cdp_ws(self, request):
        ws = web.WebSocketResponse(max_msg_size=0)
        await ws.prepare(request)
        self._ws = ws
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                cmd = json.loads(msg.data)
                self.received.append((cmd["method"], cmd.get("params", {})))
                result = self._handle(cmd["method"], cmd.get("params", {}))
                await ws.send_json({"id": cmd["id"], "result": result})
        return ws

    def _handle(self, method, params):
        if method == "Runtime.evaluate":
            expr = params.get("expression", "")
            if "location.href" in expr:
                return {"result": {"type": "string", "value": self.page_url}}
            return {"result": {"type": "object", "value": self.eval_result}}
        if method == "Page.addScriptToEvaluateOnNewDocument":
            self._script_n += 1
            return {"identifier": f"script-{self._script_n}"}
        return {}

    async def emit_binding(self, payload, name="lumSend"):
        """Simulate the page calling window.lumSend(payload)."""
        assert self._ws is not None, "no CDP client connected to the fake browser"
        await self._ws.send_json({
            "method": "Runtime.bindingCalled",
            "params": {"name": name, "payload": payload},
        })


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _wait_until(pred, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError(f"condition not met within {timeout}s")


async def _wait_port(port, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            _, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            return
        except OSError:
            await asyncio.sleep(0.05)
    raise TimeoutError(f"port {port} never opened")


# --------------------------------------------------------------------------
# unit tests
# --------------------------------------------------------------------------

def test_unit_helpers():
    assert _ws_remote_url("http://127.0.0.1:7773") == "ws://127.0.0.1:7773/remote"
    assert _ws_remote_url("https://host/path") == "wss://host/path/remote"

    wrapped = _wrap_exec("return 1 + 1")
    assert wrapped.startswith("(async () =>") and "return 1 + 1" in wrapped

    src = page_script("myBinding")
    assert "window.myBinding(" in src and "window._remote" in src
    print("test_unit_helpers: OK")


def test_find_target():
    async def scenario():
        port = _free_port()
        fake = FakeCDPBrowser(port, page_url="http://findme.test/page")
        await fake.start()
        try:
            target = await find_target(f"http://127.0.0.1:{port}")
            assert target["webSocketDebuggerUrl"].endswith("/devtools/page/1")

            matched = await find_target(f"http://127.0.0.1:{port}", "findme")
            assert matched["url"] == "http://findme.test/page"

            try:
                await find_target(f"http://127.0.0.1:{port}", "no-such-tab")
                assert False, "expected CDPError for a non-matching filter"
            except CDPError:
                pass
        finally:
            await fake.stop()

    asyncio.run(scenario())
    print("test_find_target: OK")


# --------------------------------------------------------------------------
# e2e — full bridge with a fake CDP browser
# --------------------------------------------------------------------------

def test_cdp_bridge_e2e():
    async def scenario():
        from loominum.server import start_server, lum
        from loominum.client import LumClient

        lum.reset()
        server_port = _free_port()
        cdp_port = _free_port()

        fake = FakeCDPBrowser(cdp_port)
        await fake.start()

        server_task = asyncio.create_task(start_server("127.0.0.1", server_port))
        await _wait_port(server_port)

        # init code registered before the sidecar connects — the server
        # replays it on the browser's 'ready'.
        lum.add_init("window.__lum_init = true;")

        transport = CDPTransport(f"http://127.0.0.1:{server_port}",
                                 debug_url=f"http://127.0.0.1:{cdp_port}")
        await transport.start()
        relay = asyncio.create_task(transport.run_forever())
        await _wait_until(lum.is_connected)
        await asyncio.sleep(0.3)  # let the init round-trip settle

        # 1. init code injected for navigation-survival
        assert any(m == "Page.addScriptToEvaluateOnNewDocument"
                   and "__lum_init" in p.get("source", "")
                   for m, p in fake.received), "init code was not injected"

        async with LumClient(url=f"http://127.0.0.1:{server_port}") as client:
            # 2. exec round-trip: client -> server -> sidecar -> (fake) browser
            fake.eval_result = 42
            result = await client.exec("return 6 * 7")
            assert result == 42, f"exec returned {result!r}"
            assert any(m == "Runtime.evaluate" and "6 * 7" in p.get("expression", "")
                       for m, p in fake.received), "exec code never reached the browser"

            # 3. event delivery: (fake) browser -> server -> client
            got = asyncio.Event()
            box = {}

            def on_hello(data):
                box.update(data)
                got.set()

            client.on("hello", on_hello)
            await fake.emit_binding(json.dumps(
                {"type": "event", "eventType": "hello", "data": {"x": 1}}))
            await asyncio.wait_for(got.wait(), timeout=3.0)
            assert box == {"x": 1}, f"event payload was {box!r}"

            # 4. navigate reaches the browser
            await client.navigate("http://example.test/next")
            await _wait_until(
                lambda: any(m == "Page.navigate" for m, _ in fake.received),
                timeout=3.0)

        await transport.close()
        for task in (relay, server_task):
            task.cancel()
        await asyncio.gather(relay, server_task, return_exceptions=True)
        await fake.stop()

    asyncio.run(scenario())
    print("test_cdp_bridge_e2e: OK")


# --------------------------------------------------------------------------
# e2e — real browser (auto-skipped when localhost:9222 is unreachable)
# --------------------------------------------------------------------------

def test_real_browser_e2e():
    async def _reachable():
        try:
            await find_target(REAL_CDP_URL)
            return True
        except Exception:
            return False

    if not asyncio.run(_reachable()):
        print(f"test_real_browser_e2e: SKIPPED (no CDP browser at {REAL_CDP_URL})")
        return

    async def scenario():
        from loominum.server import start_server, lum
        from loominum.client import LumClient

        lum.reset()
        server_port = _free_port()
        server_task = asyncio.create_task(start_server("127.0.0.1", server_port))
        await _wait_port(server_port)

        transport = CDPTransport(f"http://127.0.0.1:{server_port}",
                                 debug_url=REAL_CDP_URL)
        await transport.start()
        relay = asyncio.create_task(transport.run_forever())
        await _wait_until(lum.is_connected)

        async with LumClient(url=f"http://127.0.0.1:{server_port}") as client:
            answer = await client.exec("return 6 * 7")
            assert answer == 42, f"real browser exec returned {answer!r}"
            ua = await client.exec("return navigator.userAgent")
            print(f"  real browser UA: {ua}")

        await transport.close()
        for task in (relay, server_task):
            task.cancel()
        await asyncio.gather(relay, server_task, return_exceptions=True)

    asyncio.run(scenario())
    print("test_real_browser_e2e: OK")


if __name__ == "__main__":
    _tests = [test_unit_helpers, test_find_target,
              test_cdp_bridge_e2e, test_real_browser_e2e]
    _failed = 0
    for _t in _tests:
        try:
            _t()
        except Exception as exc:  # noqa: BLE001 — standalone runner
            _failed += 1
            import traceback
            print(f"{_t.__name__}: FAIL — {exc}")
            traceback.print_exc()
    print(f"\n{len(_tests) - _failed}/{len(_tests)} passed")
    sys.exit(1 if _failed else 0)
