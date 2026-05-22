"""
UnBilliCord Server

Combined HTTP + WebSocket server that:
- Serves static files from htdocs/ (HTTP)
- WebSocket server for remote JavaScript execution (ws://)

Browser connects once, then Python can drive the page remotely.

fetch(`${CLIENT_CONNECTION_URL}/remote.js?t=`+Date.now()).then(r=>r.text()).then(eval);

Dependencies:
    pip install aiohttp websockets
"""

import sys
import json
import time
import asyncio
import logging
import os
import ssl
import uuid

import typing as tp  # type: ignore[unusedImport]

try:
    from .common import EXEC_LISTEN_HOST, EXEC_LISTEN_PORT, CLIENT_CONNECTION_URL, EXEC_PATH_PREFIX
except ImportError:
    from common import EXEC_LISTEN_HOST, EXEC_LISTEN_PORT, CLIENT_CONNECTION_URL, EXEC_PATH_PREFIX

from pathlib import Path

import aiohttp.web
import websockets

# Check PRJ_DIR first before imports
prj_dir = os.getenv('PRJ_DIR')
if not prj_dir:
    raise RuntimeError("PRJ_DIR environment variable not set. Please run: . .init")

# Add src directory to path for imports
sys.path.insert(0, str(Path(prj_dir) / 'src'))

from unbillicord.config import UBCConfig

# Setup logging - use UnBilliCord config for log file path
try:
    ubc_config = UBCConfig()
    log_file = ubc_config.log_file
except Exception:
    log_file = 'log/ubc.log'

log_path = Path(prj_dir) / log_file
log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_path),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Get project directories
project_root = Path(prj_dir)
script_dir = Path(__file__).resolve().parent
htdocs_dir = script_dir / 'htdocs'


class RemoteUBC:
    """Manages WebSocket connections: browser and Python clients."""
    
    def __init__(self):
        self.browser_ws: tp.Optional[tp.Any] = None
        self.python_clients: set = set()
        self.pending_calls: tp.Dict[str, asyncio.Future] = {}
        self.init_code: list[str] = []  # Code to run on browser connect/reconnect
        self.event_handlers: tp.Dict[str, list] = {}  # event_type -> [handler_funcs]

        # Global API throttle state (shared across all clients)
        self._api_lock: asyncio.Lock = asyncio.Lock()
        self._last_api_time: tp.Optional[float] = None
        self._base_delay: float = 1.2  # seconds between API calls
        self._current_delay: float = 1.2
        self._consecutive_429s: int = 0
        self._throttle_increment: float = 0.2  # added per 429
    
    async def handle_connection(self, websocket):
        """Handle incoming WebSocket connection (browser or Python client)."""
        # Get path from websocket request
        path = websocket.request.path if hasattr(websocket, 'request') else '/remote'
        logger.info(f"Connection received on path: {path}")
        
        if path.endswith('/remote'):
            await self.handle_browser(websocket)
        elif path.endswith('/client'):
            await self.handle_python_client(websocket)
        else:
            logger.warning(f"Invalid path: {path}")
            await websocket.close(1002, "Invalid path")
    
    async def handle_browser(self, websocket):
        """Handle browser WebSocket connection."""
        print(f"🔌 Browser connected: {websocket.remote_address}")
        self.browser_ws = websocket
        
        try:
            async for message in websocket:
                data = json.loads(message)
                
                if data['type'] == 'ready':
                    print(f"✓ Browser ready: {data.get('url', 'unknown')}")
                    # Send initialization code to reset browser state
                    await self._send_init(websocket)

                elif data['type'] == 'ping':
                    # Heartbeat — respond with pong
                    await websocket.send(json.dumps({'type': 'pong', 'ts': data.get('ts', 0)}))

                elif data['type'] == 'event':
                    # Browser-initiated event
                    event_type = data.get('eventType')
                    event_data = data.get('data', {})
                    await self._dispatch_event(event_type, event_data)
                
                elif data['type'] == 'result':
                    # Result from executed code
                    call_id = data['id']
                    if call_id in self.pending_calls:
                        future = self.pending_calls[call_id]
                        if data['success']:
                            future.set_result(data.get('result'))
                        else:
                            future.set_exception(Exception(data.get('error', 'Unknown error')))
                        del self.pending_calls[call_id]
        
        except websockets.exceptions.ConnectionClosed:
            print("⚠️  Browser disconnected")
        finally:
            self.browser_ws = None
    
    async def handle_python_client(self, websocket):
        """Handle Python client WebSocket connection."""
        print(f"🐍 Python client connected: {websocket.remote_address}")
        self.python_clients.add(websocket)
        
        try:
            print(f"🐍 Waiting for messages from Python client...")
            async for message in websocket:
                print(f"🐍 Received message: {message[:100]}...")
                data = json.loads(message)
                
                if data['type'] == 'exec':
                    # Client wants to execute code in browser
                    call_id = data['id']
                    code = data['code']
                    timeout = data.get('timeout', 30.0)
                    
                    try:
                        result = await self.exec(code, timeout)
                        await websocket.send(json.dumps({
                            'type': 'result',
                            'id': call_id,
                            'success': True,
                            'result': result
                        }))
                    except Exception as e:
                        await websocket.send(json.dumps({
                            'type': 'result',
                            'id': call_id,
                            'success': False,
                            'error': str(e)
                        }))
                
                elif data['type'] == 'navigate':
                    await self.navigate(data['url'])
                    await websocket.send(json.dumps({'type': 'ok'}))

                elif data['type'] == 'api_exec':
                    # API call with global throttling
                    call_id = data['id']
                    code = data['code']
                    timeout = data.get('timeout', 30.0)

                    try:
                        result = await self.api_exec(code, timeout)
                        await websocket.send(json.dumps({
                            'type': 'result',
                            'id': call_id,
                            'success': True,
                            'result': result
                        }))
                    except Exception as e:
                        await websocket.send(json.dumps({
                            'type': 'result',
                            'id': call_id,
                            'success': False,
                            'error': str(e)
                        }))

                elif data['type'] == 'add_init':
                    self.add_init(data['code'])
                    await websocket.send(json.dumps({'type': 'ok'}))

        except websockets.exceptions.ConnectionClosed:
            print("⚠️  Python client disconnected")
        finally:
            self.python_clients.discard(websocket)

    async def exec(self, code: str, timeout: float = 30.0) -> tp.Any:
        """
        Execute JavaScript code in connected browser.
        
        Args:
            code: JavaScript code to execute
            timeout: Timeout in seconds
            
        Returns:
            Result from JavaScript execution
            
        Raises:
            Exception: If browser not connected or execution fails
        """
        if not self.browser_ws:
            raise Exception("No browser connected")
        
        call_id = str(uuid.uuid4())
        future = asyncio.Future()
        self.pending_calls[call_id] = future
        
        # Send execution request (compatible with both websockets and aiohttp)
        message = json.dumps({
            'type': 'exec',
            'id': call_id,
            'code': code
        })
        
        if hasattr(self.browser_ws, 'send_str'):
            # aiohttp WebSocketResponse
            await self.browser_ws.send_str(message)
        else:
            # websockets library
            await self.browser_ws.send(message)
        
        # Wait for result
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            del self.pending_calls[call_id]
            raise Exception(f"Execution timed out after {timeout}s")
    
    async def api_exec(self, code: str, timeout: float = 30.0) -> tp.Any:
        """
        Execute JS in browser with global API throttling.

        Serializes all API calls through a single lock, enforcing a minimum
        delay between requests. Adjusts delay upward on 429 responses.
        All clients share this throttle -- prevents alternating calls from
        defeating backoff.

        Args:
            code: JavaScript code to execute
            timeout: Timeout in seconds

        Returns:
            Result from JavaScript execution
        """
        async with self._api_lock:
            now: float = time.monotonic()
            if self._last_api_time is not None:
                elapsed: float = now - self._last_api_time
                remaining: float = self._current_delay - elapsed
                if remaining > 0:
                    logger.debug(f"API throttle: waiting {remaining:.2f}s")
                    await asyncio.sleep(remaining)

            self._last_api_time = time.monotonic()
            result: tp.Any = await self.exec(code, timeout)

            # Inspect result for 429 rate limiting
            if isinstance(result, dict):
                status: tp.Optional[int] = result.get('status')
                if status == 429:
                    self._consecutive_429s += 1
                    self._current_delay += self._throttle_increment
                    logger.warning(
                        f"API rate limited (429), consecutive: {self._consecutive_429s}, "
                        f"delay: {self._current_delay:.1f}s"
                    )
                else:
                    self._consecutive_429s = 0

            return result

    def is_connected(self) -> bool:
        """Check if browser is connected."""
        return self.browser_ws is not None
    
    async def navigate(self, url: str) -> None:
        """
        Navigate browser to URL.
        
        Args:
            url: URL to navigate to
        """
        if not self.browser_ws:
            raise Exception("No browser connected")
        
        # Send navigate request (compatible with both websockets and aiohttp)
        message = json.dumps({
            'type': 'navigate',
            'url': url
        })
        
        if hasattr(self.browser_ws, 'send_str'):
            # aiohttp WebSocketResponse
            await self.browser_ws.send_str(message)
        else:
            # websockets library
            await self.browser_ws.send(message)
    
    async def _send_init(self, ws: tp.Any) -> None:
        """
        Send initialization code to browser.
        
        This resets browser state by sending all registered init code.
        Called automatically when browser connects/reconnects.
        
        Args:
            ws: WebSocket connection (either aiohttp or websockets)
        """
        if not self.init_code:
            logger.info("No initialization code to send")
            return
        
        # Combine all init code
        combined_code = '\n\n'.join(self.init_code)
        
        message = json.dumps({
            'type': 'init',
            'code': combined_code
        })
        
        if hasattr(ws, 'send_str'):
            await ws.send_str(message)
        else:
            await ws.send(message)
        
        logger.info(f"Sent {len(self.init_code)} initialization block(s) to browser")
    
    async def _dispatch_event(self, event_type: str, event_data: dict) -> None:
        """
        Dispatch browser event to registered Python handlers and forward to clients.

        Args:
            event_type: Type of event (e.g., 'download_complete')
            event_data: Event payload
        """
        handlers = self.event_handlers.get(event_type, [])

        if handlers:
            logger.info(f"Dispatching event '{event_type}' to {len(handlers)} handler(s)")

            # Run all handlers concurrently
            tasks = [handler(event_data) for handler in handlers]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log any handler errors
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Handler {i} for '{event_type}' failed: {result}")

        # Forward event to all connected Python clients
        msg = json.dumps({
            'type': 'event',
            'eventType': event_type,
            'data': event_data
        })
        for client_ws in list(self.python_clients):
            try:
                if hasattr(client_ws, 'send_json'):
                    await client_ws.send_json({
                        'type': 'event',
                        'eventType': event_type,
                        'data': event_data
                    })
                else:
                    await client_ws.send(msg)
            except Exception:
                pass
    
    def add_init(self, code: str) -> None:
        """
        Register initialization code to run in browser on connect/reconnect.
        
        This code will be sent to the browser whenever it connects or reconnects,
        ensuring state is properly reset after server restarts.
        
        Args:
            code: JavaScript code to execute on initialization
            
        Example:
            ubc.add_init('''
                // Set up download observer
                window.observeDownloads = function() {
                    // ... observer code ...
                };
                observeDownloads();
            ''')
        """
        self.init_code.append(code)
        logger.info(f"Registered initialization block (total: {len(self.init_code)})")
    
    def on(self, event_type: str, handler) -> None:
        """
        Register Python event handler for browser-initiated events.
        
        Args:
            event_type: Type of event to handle (e.g., 'download_complete')
            handler: Async function to call when event occurs
            
        Example:
            async def on_download(data):
                print(f"Downloaded: {data['filename']}")
            
            ubc.on('download_complete', on_download)
        """
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        
        self.event_handlers[event_type].append(handler)
        logger.info(f"Registered handler for '{event_type}' (total: {len(self.event_handlers[event_type])})")
    
    def off(self, event_type: str, handler: tp.Optional[tp.Any] = None) -> bool:
        """
        Unregister event handler(s).
        
        Args:
            event_type: Type of event
            handler: Specific handler to remove. If None, removes all handlers for this event.
            
        Returns:
            True if handler(s) were removed, False otherwise
            
        Example:
            # Remove specific handler
            ubc.off('download_complete', my_handler)

            # Remove all handlers for event type
            ubc.off('download_complete')
        """
        if event_type not in self.event_handlers:
            logger.warning(f"No handlers registered for '{event_type}'")
            return False
        
        if handler is None:
            # Remove all handlers for this event type
            count = len(self.event_handlers[event_type])
            del self.event_handlers[event_type]
            logger.info(f"Removed all {count} handler(s) for '{event_type}'")
            return True
        else:
            # Remove specific handler
            try:
                self.event_handlers[event_type].remove(handler)
                logger.info(f"Removed handler for '{event_type}' (remaining: {len(self.event_handlers[event_type])})")
                
                # Clean up empty handler lists
                if not self.event_handlers[event_type]:
                    del self.event_handlers[event_type]
                
                return True
            except ValueError:
                logger.warning(f"Handler not found for '{event_type}'")
                return False
    
    def clear_handlers(self) -> int:
        """
        Clear all event handlers.
        
        Returns:
            Number of event types that had handlers
            
        Example:
            ubc.clear_handlers()
        """
        count = len(self.event_handlers)
        self.event_handlers.clear()
        logger.info(f"Cleared all event handlers ({count} event type(s))")
        return count
    
    def clear_init(self) -> int:
        """
        Clear all initialization code.
        
        Returns:
            Number of init blocks that were cleared
            
        Example:
            ubc.clear_init()
        """
        count = len(self.init_code)
        self.init_code.clear()
        logger.info(f"Cleared all initialization code ({count} block(s))")
        return count
    
    def reset(self) -> tuple[int, int]:
        """
        Reset all handlers and initialization code.
        
        Useful for testing or when you want a clean slate.
        
        Returns:
            Tuple of (event_types_cleared, init_blocks_cleared)
            
        Example:
            ubc.reset()
        """
        events_cleared = self.clear_handlers()
        init_cleared = self.clear_init()
        logger.info(f"Reset complete: {events_cleared} event type(s), {init_cleared} init block(s)")
        return (events_cleared, init_cleared)
    
    async def handle_browser_aio(self, ws):
        """Handle browser WebSocket connection (aiohttp version)."""
        logger.info(f"🔌 Browser connected (aiohttp)")
        self.browser_ws = ws
        
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    if data['type'] == 'ready':
                        logger.info(f"✓ Browser ready: {data.get('url', 'unknown')}")
                        # Send initialization code to reset browser state
                        await self._send_init(ws)

                    elif data['type'] == 'ping':
                        # Heartbeat — respond with pong
                        await ws.send_json({'type': 'pong', 'ts': data.get('ts', 0)})

                    elif data['type'] == 'event':
                        # Browser-initiated event
                        event_type = data.get('eventType')
                        event_data = data.get('data', {})
                        await self._dispatch_event(event_type, event_data)
                    
                    elif data['type'] == 'result':
                        # Result from executed code
                        call_id = data['id']
                        if call_id in self.pending_calls:
                            future = self.pending_calls[call_id]
                            if data['success']:
                                future.set_result(data.get('result'))
                            else:
                                future.set_exception(Exception(data.get('error', 'Unknown error')))
                            del self.pending_calls[call_id]
                
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.warning(f'⚠️ WebSocket error: {ws.exception()}')
        
        except Exception as e:
            logger.info(f"⚠️ Browser disconnected (error): {e}")
        finally:
            if self.browser_ws is ws:
                logger.info("🔌 Browser connection closed (was active)")
                self.browser_ws = None
            else:
                logger.info("🔌 Browser connection closed (stale — newer connection active)")
    
    async def handle_python_client_aio(self, ws):
        """Handle Python client WebSocket connection (aiohttp version)."""
        logger.info(f"🐍 Python client connected (aiohttp)")
        self.python_clients.add(ws)
        
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    if data['type'] == 'exec':
                        # Client wants to execute code in browser
                        call_id = data['id']
                        code = data['code']
                        timeout = data.get('timeout', 30.0)
                        
                        try:
                            result = await self.exec(code, timeout)
                            await ws.send_json({
                                'type': 'result',
                                'id': call_id,
                                'success': True,
                                'result': result
                            })
                        except Exception as e:
                            await ws.send_json({
                                'type': 'result',
                                'id': call_id,
                                'success': False,
                                'error': str(e)
                            })
                    
                    elif data['type'] == 'api_exec':
                        # API call with global throttling
                        call_id = data['id']
                        code = data['code']
                        timeout = data.get('timeout', 30.0)

                        try:
                            result = await self.api_exec(code, timeout)
                            await ws.send_json({
                                'type': 'result',
                                'id': call_id,
                                'success': True,
                                'result': result
                            })
                        except Exception as e:
                            await ws.send_json({
                                'type': 'result',
                                'id': call_id,
                                'success': False,
                                'error': str(e)
                            })

                    elif data['type'] == 'navigate':
                        await self.navigate(data['url'])
                        await ws.send_json({'type': 'ok'})

                    elif data['type'] == 'add_init':
                        self.add_init(data['code'])
                        await ws.send_json({'type': 'ok'})

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f'⚠️ WebSocket error: {ws.exception()}')

        except Exception as e:
            print(f"⚠️ Python client disconnected: {e}")
        finally:
            self.python_clients.discard(ws)


async def handle_websocket(request):
    """Handle WebSocket connections (both /remote and /client)."""
    path = request.path
    logger.info(f"WebSocket connection attempt on path: {path} from {request.remote}")
    
    ws = aiohttp.web.WebSocketResponse()
    await ws.prepare(request)
    
    if path.endswith('/remote'):
        await ubc.handle_browser_aio(ws)
    elif path.endswith('/client'):
        await ubc.handle_python_client_aio(ws)
    else:
        logger.warning(f"Invalid WebSocket path: {path}")
        await ws.close(code=1002, message=b'Invalid path')
    
    return ws


async def handle_cert_pem(request):
    """Serve the raw certificate file for manual installation."""
    assert prj_dir is not None, "PRJ_DIR not set"
    prj_dir_path = Path(prj_dir)
    cert_file = prj_dir_path / 'data' / 'unbillicord' / 'cert.pem'

    if not cert_file.exists():
        return aiohttp.web.Response(
            text="Error: No SSL certificate found.",
            status=404
        )
    
    with open(cert_file, 'r') as f:
        cert_content = f.read()
    
    return aiohttp.web.Response(
        text=cert_content,
        content_type='application/x-pem-file',
        headers={
            'Content-Disposition': 'attachment; filename="ubc.pem"',
            'Cache-Control': 'no-store, no-cache, must-revalidate',
            'Access-Control-Allow-Origin': '*'
        }
    )


async def handle_verify(request):
    """Serve a simple verification page to confirm SSL is working."""
    scheme = 'https' if request.scheme == 'https' else 'http'
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>UnBilliCord Server - Connection Verified</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .card {{
            background: white;
            border-radius: 8px;
            padding: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2ecc71;
            margin-top: 0;
        }}
        .status {{
            background: #d4edda;
            border: 1px solid #c3e6cb;
            color: #155724;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
        }}
        .info {{
            background: #e7f3ff;
            border: 1px solid #b3d9ff;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
        .command {{
            background: #2c3e50;
            color: #ecf0f1;
            padding: 15px;
            border-radius: 4px;
            margin: 10px 0;
            overflow-x: auto;
        }}
        ul {{
            line-height: 1.8;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>✓ Certificate Verification Confirmed!</h1>
        
        <div class="status">
            <strong>Connection Status:</strong> {scheme.upper()} connection established successfully<br>
            <strong>Server:</strong> UnBilliCord Server<br>
            <strong>Endpoint:</strong> {request.url}
        </div>
        
        <div class="info">
            <h3>Next Steps:</h3>
            <ol>
                <li>Navigate to the site you want to drive and log in</li>
                <li>Open the browser console (press <code>F12</code>)</li>
                <li>Paste and run this command:</li>
            </ol>
            <div class="command">
                fetch('{CLIENT_CONNECTION_URL}/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);
            </div>
            <p>You should see: <code>✓ Connected to UnBilliCord</code></p>
        </div>
        
        <h3>Available Endpoints:</h3>
        <ul>
            <li><code>/remote.js</code> - Browser WebSocket client</li>
            <li><code>/install-cert.sh</code> - Linux certificate installer</li>
            <li><code>/install-cert.ps1</code> - Windows certificate installer</li>
            <li><code>/cert.pem</code> - Raw certificate file</li>
        </ul>
    </div>
</body>
</html>"""
    
    return aiohttp.web.Response(
        text=html,
        content_type='text/html',
        headers={
            'Cache-Control': 'no-store, no-cache, must-revalidate',
            'Access-Control-Allow-Origin': '*'
        }
    )


async def handle_remote_js(request):
    """Serve remote.js with dynamically injected server URL."""
    # Use CLIENT_CONNECTION_URL if configured, otherwise fall back to Host header
    if CLIENT_CONNECTION_URL:
        server_url = CLIENT_CONNECTION_URL
    else:
        host = request.headers.get('Host', f'http://localhost:{EXEC_LISTEN_PORT}')
        server_url = f"http://{host}" if not host.startswith('http') else host
    
    # Read the remote.js file
    remote_js_path = htdocs_dir / 'remote.js'
    with open(remote_js_path, 'r') as f:
        content = f.read()
    
    # Inject the server URL by setting window.EXEC_SERVER before the script runs
    injected_content = f"window.EXEC_SERVER = window.EXEC_SERVER || '{server_url}';\n{content}"
    
    return aiohttp.web.Response(
        text=injected_content,
        content_type='application/javascript',
        headers={
            'Cache-Control': 'no-store, no-cache, must-revalidate',
            'Access-Control-Allow-Origin': '*'
        }
    )


# Global UBC instance
ubc = RemoteUBC()


async def start_server(
    listen_host=EXEC_LISTEN_HOST,
    listen_port=EXEC_LISTEN_PORT
):
    """Start combined HTTP + WebSocket server using aiohttp."""
    # Determine the client connection URL
    if CLIENT_CONNECTION_URL:
        display_url = CLIENT_CONNECTION_URL
    else:
        display_url = f"http://localhost:{listen_port}"
    
    logger.info("=" * 60)
    logger.info("🚀 UnBilliCord Server")
    logger.info("=" * 60)
    logger.info(f"Listening on:     {listen_host}:{listen_port}")
    logger.info(f"Client URL:       {display_url}")
    logger.info(f"Serving from:     {htdocs_dir}")
    logger.info("")
    logger.info("Paste one of the following into the browser console.")
    logger.info("")
    logger.info("Connect a browser:")
    logger.info("-" * 60)
    logger.info(f"fetch('{display_url}/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);")
    logger.info("-" * 60)
    logger.info("")
    logger.info("Enable event logging:")
    logger.info("-" * 60)
    logger.info(f"fetch('{display_url}/evtcap.js?t='+Date.now()).then(r=>r.text()).then(eval);")
    logger.info("-" * 60)
    logger.info("")
    
    # Create aiohttp application
    app = aiohttp.web.Application()
    
    # Add routes with path prefix support
    prefix = EXEC_PATH_PREFIX
    app.router.add_get(f'{prefix}/remote', handle_websocket)
    app.router.add_get(f'{prefix}/client', handle_websocket)
    app.router.add_get(f'{prefix}/remote.js', handle_remote_js)  # Dynamic injection
    
    # SSL certificate endpoint (raw cert.pem from data/)
    app.router.add_get(f'{prefix}/cert.pem', handle_cert_pem)
    
    # Verification page (root path)
    if prefix:
        app.router.add_get(f'{prefix}/', handle_verify)
        app.router.add_get(f'{prefix}', handle_verify)
    else:
        app.router.add_get('/', handle_verify)
    
    # Serve static files from htdocs (includes install-cert.sh, install-cert.ps1, check-cert.ps1)
    if prefix:
        app.router.add_static(f'{prefix}/', htdocs_dir, show_index=False)
    else:
        app.router.add_static('/', htdocs_dir, show_index=False)
    
    # Add CORS middleware
    @aiohttp.web.middleware
    async def cors_middleware(request, handler):
        response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = '*'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return response
    
    app.middlewares.append(cors_middleware)
    
    # SSL context (if certificate exists)
    ssl_context = None
    assert prj_dir is not None, "PRJ_DIR not set"
    prj_dir_path = Path(prj_dir)
    cert_dir = prj_dir_path / 'data' / 'unbillicord'
    cert_file = cert_dir / 'cert.pem'
    key_file = cert_dir / 'key.pem'
    
    if cert_file.exists() and key_file.exists():
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(cert_file, key_file)
        logger.info(f"✓ SSL enabled (using {cert_file})")
    else:
        logger.info(f"SSL disabled (no cert found at {cert_file})")
    
    # Start server
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, listen_host, listen_port, ssl_context=ssl_context)
    await site.start()
    
    # Run forever
    await asyncio.Future()


async def example_usage():
    """
    Example of how to use UnBilliCord.

    Infrastructure only — application logic builds on top of exec()/navigate().
    """

    # Wait for browser to connect
    print("\nWaiting for browser connection...")
    while not ubc.is_connected():
        await asyncio.sleep(0.5)

    print("✓ Browser connected!\n")

    # Navigate to a page
    print("🧭 Navigating...")
    await ubc.navigate('https://example.com')
    await asyncio.sleep(2)

    # Low-level JavaScript execution
    result = await ubc.exec("return document.title")
    print(f"Page title: {result}")


def main():
    """Console-script entrypoint (the `ubc` command)."""
    asyncio.run(start_server())


if __name__ == '__main__':
    main()
