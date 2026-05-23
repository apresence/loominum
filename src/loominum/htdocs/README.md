# Loominum Server Endpoints

## Browser Connection

Connect a browser to the Loominum server:
```javascript
fetch('https://tau:7993/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);
```

Enable event logging:
```javascript
fetch('https://tau:7993/evtcap.js?t='+Date.now()).then(r=>r.text()).then(eval);
```

## SSL Certificate Installation

### One-Liner Installation (Recommended)

**Linux (run as root):**
```bash
curl -k https://tau:7993/install-cert.sh | sudo bash
```

**Windows (PowerShell as Administrator):**
```powershell
curl.exe -k https://tau:7993/install-cert.ps1 | powershell -ExecutionPolicy Bypass -Command -
```

### Manual Installation

Download certificate:
```
https://tau:7993/cert.pem
```

Then import in browser:
- **Edge/Chrome**: `edge://settings/certificates` → Authorities → Import
- **Firefox**: `about:preferences#privacy` → Certificates → Authorities → Import

## Available Endpoints

- `/remote.js` - Browser client script (auto-injected server URL)
- `/evtcap.js` - Event capture/logging script
- `/install-cert.sh` - Linux cert installer (embedded certificate)
- `/install-cert.ps1` - Windows cert installer (embedded certificate)
- `/cert.pem` - Raw certificate file for manual installation
- `/remote` - WebSocket endpoint for browser
- `/client` - WebSocket endpoint for Python clients

## Notes

- Installation scripts embed the certificate content, so you only need to download and run one file
- The `-k` flag in curl bypasses SSL verification for the initial download (needed since cert isn't trusted yet)
- After installation, all future connections will be properly verified
- Firefox uses a separate certificate store and requires manual import
