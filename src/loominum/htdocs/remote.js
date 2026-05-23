// Loominum — browser-side remote JavaScript bridge
// Connects to Python server via WebSocket and executes commands

(async function initRemote() {
    const conlog = console.log.bind(console);
    const conerr = console.error.bind(console);

    const SERVER_URL = window.EXEC_SERVER || 'http://localhost:7773';

    let WS_URL;
    if (SERVER_URL.startsWith('http://') || SERVER_URL.startsWith('https://')) {
        const url = new URL(SERVER_URL);
        const wsProtocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
        WS_URL = `${wsProtocol}//${url.host}${url.pathname}/remote`.replace(/\/+/g, '/').replace(':/', '://');
    } else {
        WS_URL = `ws://${SERVER_URL}/remote`;
    }

    let ws = null;
    let reconnectAttempts = 0;
    let lastReconnectLog = 0;
    let lastErrorLog = 0;
    let heartbeatInterval = null;
    let lastPong = 0;

    const RECONNECT_INTERVAL = 5000;
    const LOG_INTERVAL = 5 * 60 * 1000;
    const HEARTBEAT_INTERVAL = 30000;
    const HEARTBEAT_TIMEOUT = 15000;

    const state = {
        observers: [], intervals: [], timeouts: [], listeners: [], cleanup: []
    };

    function cleanupState() {
        state.observers.forEach(obs => obs.disconnect());
        state.intervals.forEach(id => clearInterval(id));
        state.timeouts.forEach(id => clearTimeout(id));
        state.listeners.forEach(({element, event, handler}) => {
            element.removeEventListener(event, handler);
        });
        state.cleanup.forEach(fn => fn());
        state.observers = [];
        state.intervals = [];
        state.timeouts = [];
        state.listeners = [];
        state.cleanup = [];
        conlog('🧹 Cleaned up browser state');
    }

    const _nonce = document.querySelector('script[nonce]')?.nonce || '';

    async function safeExec(code, isAsync = true) {
        return new Promise((resolve, reject) => {
            const callbackId = '_exec_' + Math.random().toString(36).slice(2);
            window[callbackId] = { resolve, reject };
            const s = document.createElement('script');
            if (_nonce) s.nonce = _nonce;
            if (isAsync) {
                s.textContent = `(async()=>{try{const __r=await(async()=>{${code}})();window['${callbackId}'].resolve(__r)}catch(e){window['${callbackId}'].reject(e)}finally{delete window['${callbackId}']}})()`;
            } else {
                s.textContent = `try{const __r=(()=>{${code}})();window['${callbackId}'].resolve(__r)}catch(e){window['${callbackId}'].reject(e)}finally{delete window['${callbackId}']}`;
            }
            document.documentElement.appendChild(s);
            s.remove();
        });
    }

    window._remote = {
        emit: (eventType, data = {}) => {
            if (!ws || ws.readyState !== WebSocket.OPEN) {
                conerr('❌ Cannot emit event - WebSocket not connected');
                return false;
            }
            ws.send(JSON.stringify({type: 'event', eventType, data}));
            return true;
        },
        addObserver: (observer) => state.observers.push(observer),
        addInterval: (id) => state.intervals.push(id),
        addTimeout: (id) => state.timeouts.push(id),
        addListener: (element, event, handler) => {
            element.addEventListener(event, handler);
            state.listeners.push({element, event, handler});
        },
        addCleanup: (fn) => state.cleanup.push(fn),
        cleanup: cleanupState
    };

    function connect() {
        const now = Date.now();
        if (reconnectAttempts === 0) {
            conlog(`🔌 Connecting to Loominum (${WS_URL})...`);
        } else if (now - lastReconnectLog >= LOG_INTERVAL) {
            conlog(`🔌 Still attempting to connect... (${reconnectAttempts} attempts)`);
            lastReconnectLog = now;
        }

        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            if (reconnectAttempts > 0) {
                conlog(`✓ Reconnected to Loominum (after ${reconnectAttempts} attempts)`);
            } else {
                conlog('✓ Connected to Loominum');
            }
            conlog('   Python can now send commands to this browser session');

            cleanupState();

            reconnectAttempts = 0;
            lastReconnectLog = 0;
            lastPong = Date.now();

            if (heartbeatInterval) clearInterval(heartbeatInterval);
            heartbeatInterval = setInterval(() => {
                if (!ws || ws.readyState !== WebSocket.OPEN) return;
                if (Date.now() - lastPong > HEARTBEAT_INTERVAL + HEARTBEAT_TIMEOUT) {
                    conlog('⚠️  Heartbeat timeout — connection dead, forcing reconnect');
                    if (heartbeatInterval) clearInterval(heartbeatInterval);
                    heartbeatInterval = null;
                    ws.close();
                    return;
                }
                ws.send(JSON.stringify({type: 'ping', ts: Date.now()}));
            }, HEARTBEAT_INTERVAL);

            ws.send(JSON.stringify({type: 'ready', url: window.location.href}));
        };

        ws.onmessage = async (event) => {
            try {
                const msg = JSON.parse(event.data);

                if (msg.type === 'pong') {
                    lastPong = Date.now();
                }
                else if (msg.type === 'init') {
                    conlog('⚡ Running initialization code from server');
                    try {
                        await safeExec(msg.code);
                        conlog('✓ Initialization complete');
                    } catch (error) {
                        conerr('❌ Initialization failed:', error);
                    }
                }
                else if (msg.type === 'exec') {
                    const preview = msg.code.replace(/\s+/g, ' ').substring(0, 80);
                    conlog(`⚡ exec [${msg.id}]: ${preview}...`);
                    try {
                        const result = await safeExec(msg.code);
                        conlog(`✓ exec [${msg.id}] ok:`, typeof result === 'object' ? JSON.stringify(result).substring(0, 120) : result);
                        ws.send(JSON.stringify({
                            type: 'result', id: msg.id, success: true, result: result
                        }));
                    } catch (error) {
                        conerr(`❌ exec [${msg.id}] failed:`, error.message);
                        ws.send(JSON.stringify({
                            type: 'result', id: msg.id, success: false,
                            error: error.message, stack: error.stack
                        }));
                    }
                }
                else if (msg.type === 'navigate') {
                    conlog(`🧭 Navigating to: ${msg.url}`);
                    window.location.href = msg.url;
                }
            } catch (error) {
                conerr('❌ Error processing message:', error);
            }
        };

        ws.onerror = (error) => {
            const now = Date.now();
            if (reconnectAttempts === 0) {
                conerr('❌ WebSocket error:', error);
                lastErrorLog = now;
            } else if (now - lastErrorLog >= LOG_INTERVAL) {
                conerr(`❌ WebSocket error (${reconnectAttempts} attempts):`, error);
                lastErrorLog = now;
            }
        };

        ws.onclose = (event) => {
            if (heartbeatInterval) {
                clearInterval(heartbeatInterval);
                heartbeatInterval = null;
            }
            conlog(`⚠️  Disconnected from Loominum (code: ${event.code}, reason: ${event.reason || 'none'}, clean: ${event.wasClean})`);
            reconnectAttempts++;
            setTimeout(connect, RECONNECT_INTERVAL);
        };

        window._remoteWS = ws;
    }

    connect();

})();
