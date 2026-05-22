# Browser Event System

UnBilliCord supports bidirectional event-driven communication:
- **Python → Browser**: Execute code, navigate, initialize state
- **Browser → Python**: Emit events based on DOM changes, user actions, or conditions

## Architecture

When the server restarts, all initialization code is automatically re-sent to the browser, resetting event handlers and observers.

## Usage

### 1. Register Initialization Code (Python)

```python
from unbillicord.server import ubc

# Set up browser-side observer
ubc.add_init('''
    // Observe download completions
    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            for (const node of mutation.addedNodes) {
                if (node.tagName === 'A' && node.download) {
                    window._remote.emit('download_ready', {
                        filename: node.download,
                        url: node.href
                    });
                }
            }
        }
    });
    
    observer.observe(document.body, {childList: true, subtree: true});
    window._remote.addObserver(observer);  // Register for cleanup
''')
```

### 2. Register Event Handler (Python)

```python
async def on_download_ready(data):
    filename = data['filename']
    print(f"Download ready: {filename}")
    # Process the file...

ubc.on('download_ready', on_download_ready)
```

### 3. Emit Events (Browser)

Initialization code can use `window._remote.emit()`:

```javascript
// In init code
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('download-btn')) {
        window._remote.emit('download_clicked', {
            clipId: e.target.dataset.clipId
        });
    }
});
```

Or in ad-hoc executed code:

```python
# Python triggers browser check
result = await ubc.exec('''
    const incomplete = document.querySelectorAll('.pending-download');
    if (incomplete.length > 0) {
        window._remote.emit('downloads_pending', {
            count: incomplete.length
        });
    }
    return incomplete.length;
''')
```

## State Management

The browser-side `window._remote` provides cleanup tracking:

```javascript
// Auto-cleanup on reconnect
window._remote.addObserver(observer);          // MutationObserver
window._remote.addInterval(intervalId);        // setInterval
window._remote.addTimeout(timeoutId);          // setTimeout
window._remote.addListener(el, 'click', fn);   // addEventListener (auto-attached)
window._remote.addCleanup(() => {...});        // Custom cleanup
```

When the server restarts or browser reconnects:
1. All tracked state is cleaned up
2. Initialization code is re-sent
3. Event handlers are re-registered

## Complete Example

```python
# setup_download_monitor.py
from unbillicord.server import ubc

# Browser-side: Watch for download links
ubc.add_init('''
    function watchDownloads() {
        const observer = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.tagName === 'A' && node.classList.contains('download-link')) {
                        window._remote.emit('download_appeared', {
                            filename: node.textContent,
                            url: node.href,
                            clipId: node.dataset.clipId
                        });
                    }
                }
            }
        });
        
        observer.observe(document.body, {childList: true, subtree: true});
        window._remote.addObserver(observer);
        
        console.log('✓ Download monitor active');
    }
    
    watchDownloads();
''')

# Python-side: Handle download events
async def handle_download_appeared(data):
    print(f"Download appeared: {data['filename']}")
    
    # Trigger the download
    await ubc.exec(f'''
        const link = document.querySelector(`a[data-clip-id="{data['clipId']}"]`);
        link.click();
    ''')

async def handle_download_complete(data):
    print(f"Download complete: {data['filename']}")
    # Move file to clips directory
    await move_file(data['filename'])

ubc.on('download_appeared', handle_download_appeared)
ubc.on('download_complete', handle_download_complete)
```

## Pattern: Polling with Cleanup

```python
ubc.add_init('''
    function pollForElement(selector, callback, interval = 1000) {
        const id = setInterval(() => {
            const el = document.querySelector(selector);
            if (el) {
                clearInterval(id);
                callback(el);
            }
        }, interval);
        
        window._remote.addInterval(id);
        return id;
    }
    
    pollForElement('.status-indicator', (el) => {
        window._remote.emit('status_ready', {status: el.textContent});
    });
''')
```

## Best Practices

1. **Always register cleanup**: Use `window._remote.add*()` for all persistent state
2. **Keep init code idempotent**: It may run multiple times on reconnects
3. **Handle missing elements gracefully**: Browser state may change between reconnects
4. **Use async handlers**: Python handlers should be async functions
5. **Batch related events**: Don't emit on every keystroke; debounce/throttle
