# NGINX Reverse Proxy Setup for Loominum

This guide explains how to configure NGINX to forward external HTTPS connections to the local Loominum server.

> **Alternative:** If you don't have NGINX, see [Self-Signed SSL Certificate](#self-signed-ssl-certificate) below for running Loominum with HTTPS directly.

## Overview

The setup forwards:
- External: `https://nginxhost.somewhere.com/lum` → Internal: `http://127.0.0.1:7773`
- Supports both HTTP requests and WebSocket connections

## Prerequisites

- NGINX installed on your server
- SSL certificate for your domain (e.g., via Let's Encrypt)
- Loominum server running on `127.0.0.1:7773`

## NGINX Configuration

Add the following to your NGINX site configuration (typically in `/etc/nginx/sites-available/your-domain`):

```nginx
# Loominum reverse proxy configuration
location /lum/ {
    # Proxy to local Loominum server
    proxy_pass http://127.0.0.1:7773/;
    
    # WebSocket support
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # Forward original request headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Port $server_port;
    
    # Timeouts for long-running WebSocket connections
    proxy_connect_timeout 7d;
    proxy_send_timeout 7d;
    proxy_read_timeout 7d;
    
    # Disable buffering for real-time communication
    proxy_buffering off;
    
    # CORS headers (if needed for cross-origin access)
    add_header Access-Control-Allow-Origin * always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
    add_header Access-Control-Allow-Headers "*" always;
}
```

## Complete Example

Here's a complete NGINX server block example with SSL:

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name nginxhost.somewhere.com;
    
    # SSL configuration
    ssl_certificate /etc/letsencrypt/live/nginxhost.somewhere.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/nginxhost.somewhere.com/privkey.pem;
    
    # SSL settings (recommended)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    
    # Loominum reverse proxy
    location /lum/ {
        proxy_pass http://127.0.0.1:7773/;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Forward original request headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # Timeouts for long-running WebSocket connections
        proxy_connect_timeout 7d;
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
        
        # Disable buffering for real-time communication
        proxy_buffering off;
        
        # CORS headers
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "*" always;
    }
    
    # Other locations for your domain...
}

# HTTP to HTTPS redirect
server {
    listen 80;
    listen [::]:80;
    server_name nginxhost.somewhere.com;
    return 301 https://$server_name$request_uri;
}
```

## Configuration Steps

1. **Create or edit NGINX configuration:**
   ```bash
   sudo nano /etc/nginx/sites-available/your-domain
   ```

2. **Add Loominum location block** to your server configuration (see above)

3. **Test NGINX configuration:**
   ```bash
   sudo nginx -t
   ```

4. **Reload NGINX:**
   ```bash
   sudo systemctl reload nginx
   ```

5. **Update `common.py` with your public URL:**
   ```python
   CLIENT_CONNECTION_URL = 'https://nginxhost.somewhere.com/lum'
   ```

6. **Start Loominum server:**
   ```bash
   python src/loominum/server.py
   ```

## Testing the Setup

### Test HTTP endpoint
```bash
curl https://nginxhost.somewhere.com/lum/cert.pem
```

### Test WebSocket connection (browser console)
```javascript
fetch('https://nginxhost.somewhere.com/lum/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);
```

## Troubleshooting

### WebSocket connection fails

Check NGINX error logs:
```bash
sudo tail -f /var/log/nginx/error.log
```

Verify WebSocket upgrade headers are being passed:
```bash
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: test" \
  https://nginxhost.somewhere.com/lum/remote
```

### 502 Bad Gateway

- Ensure the Loominum server is running: `ps aux | grep loominum`
- Check if server is listening: `netstat -tlnp | grep 7773`
- Verify firewall allows local connections

### CORS errors

Make sure CORS headers are included in the NGINX configuration (see above).

## Security Considerations

1. **Firewall:** Ensure port 7773 is NOT exposed externally (only localhost)
   ```bash
   sudo ufw deny 7773
   ```

2. **Authentication:** Consider adding HTTP basic auth to the `/lum/` location:
   ```nginx
   location /lum/ {
       auth_basic "Loominum Access";
       auth_basic_user_file /etc/nginx/.htpasswd;
       # ... rest of config
   }
   ```

3. **IP Whitelisting:** Restrict access to specific IPs:
   ```nginx
   location /lum/ {
       allow 203.0.113.0/24;  # Your IP range
       deny all;
       # ... rest of config
   }
   ```

## URL Mapping

| External URL | Internal URL | Description |
|--------------|--------------|-------------|
| `https://nginxhost.somewhere.com/lum/remote.js` | `http://127.0.0.1:7773/remote.js` | Browser script |
| `wss://nginxhost.somewhere.com/lum/remote` | `ws://127.0.0.1:7773/remote` | Browser WebSocket |
| `wss://nginxhost.somewhere.com/lum/client` | `ws://127.0.0.1:7773/client` | Python client WebSocket |

## Notes

- The trailing slash in `proxy_pass http://127.0.0.1:7773/;` is important - it strips the `/lum` prefix
- WebSocket connections can stay open for days - set appropriate timeouts
- Monitor NGINX logs in `/var/log/nginx/` for debugging

---

# Self-Signed SSL Certificate

If you don't have NGINX but want to use wss:// (secure WebSocket), you can configure Loominum server to use a self-signed certificate directly.

## Quick Start

```bash
# 1. Configure hostname (edit data/loominum/config.json)
#    Set "lum_hostname" to your server's hostname/IP
#    Example: "lum_hostname": "myserver.local"
#    Or:      "lum_hostname": "192.168.1.100"

# 2. Generate certificate (reads hostname from config)
cd /mnt/global/prj/dev/loominum/src/loominum
./gencert.sh

# 3. Trust certificate in browser (see below)

# 4. Start server (will auto-detect cert and use SSL)
python server.py

# 5. Connect from browser (uses hostname from config)
#    Server will display the exact command to copy/paste
```

## Detailed Steps

### 0. Configure Hostname

Edit `data/loominum/config.json` and set the `lum_hostname` field to your server's hostname or IP address:

```json
{
  "lum_hostname": "myserver.local",
  // ... other settings
}
```

Or for an IP address:
```json
{
  "lum_hostname": "192.168.1.100",
  // ... other settings
}
```

This hostname will be:
- Used in the SSL certificate's CN and SAN
- Displayed in the server startup instructions
- Used in the browser connection URL

### 1. Generate Self-Signed Certificate

Run the provided script:
```bash
util/gencert.py
```

The script automatically reads `lum_hostname` from `data/loominum/config.json` and includes it in the certificate.

**To add additional hostnames/IPs**, pass them as arguments:
```bash
# Config has "lum_hostname": "myserver.local"
# But also want to access via IP
./src/loominum/gencert.sh 192.168.1.100

# Add multiple additional SANs
./src/loominum/gencert.sh another-name.local 10.0.0.50
```

Or manually:
```bash
# Replace myserver.local with your actual hostname
openssl req -x509 -newkey rsa:4096 \
  -keyout key.pem \
  -out cert.pem \
  -days 365 -nodes \
  -subj "/CN=myserver.local" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,DNS:myserver.local,IP:192.168.1.100"
#                                                                      ^^^^ Add your hostname/IPs
```

This creates:
- `src/loominum/certs/cert.pem` - Public certificate
- `src/loominum/certs/key.pem` - Private key

**Important:** The certificate's Subject Alternative Names (SANs) must match the hostname/IP you use to access the server
- `src/loominum/certs/key.pem` - Private key

**Important:** The certificate's Subject Alternative Names (SANs) must match the hostname/IP you use to access the server. If you access via `https://192.168.1.100:7993`, the certificate must include `IP:192.168.1.100`.

### 2. Trust Certificate in Browser

The browser will warn about the self-signed certificate until you trust it.

**Chrome/Chromium/Edge:**
1. Navigate to `chrome://settings/certificates` (or `edge://settings/certificates`)
2. Click **Authorities** tab
3. Click **Import**
4. Select `src/loominum/certs/cert.pem`
5. Check "Trust this certificate for identifying websites"
6. Click OK

**Firefox:**
1. Navigate to `about:preferences#privacy`
2. Scroll to **Certificates** section
3. Click **View Certificates**
4. Click **Authorities** tab
5. Click **Import**
6. Select `src/loominum/certs/cert.pem`
7. Check "Trust this CA to identify websites"
8. Click OK

**Safari (macOS):**
1. Open Keychain Access
2. Select "System" keychain
3. Drag `cert.pem` into the keychain
4. Double-click the certificate
5. Expand "Trust" section
6. Set "When using this certificate" to "Always Trust"

### 3. Server Configuration

The server automatically detects the certificate files:

```python
# In server.py - automatically enabled if cert exists
cert_dir = Path(__file__).parent / 'certs'
cert_file = cert_dir / 'cert.pem'
key_file = cert_dir / 'key.pem'

if cert_file.exists() and key_file.exists():
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(cert_file, key_file)
    # Server runs with https:// and wss://
```

The hostname is configured in `data/loominum/config.json`:
```json
{
  "lum_hostname": "myserver.local"
}
```

This value is used to construct the connection URL shown at server startup.

### 4. Start Server

```bash
python src/loominum/server.py
```

You should see:
```
✓ SSL enabled (using /path/to/certs/cert.pem)
Server started: https://myserver.local:7993
...
fetch('https://myserver.local:7993/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);
```

### 5. Connect from Browser

Copy/paste the command shown in the server startup output (it will use the hostname from your config).

```javascript
// Example (hostname depends on your config)
fetch('https://myserver.local:7993/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);
```

If the certificate is trusted, this will connect without warnings.

## Troubleshooting

### "Your connection is not private" (NET::ERR_CERT_AUTHORITY_INVALID)

**Cause:** The certificate hasn't been trusted yet.
**Fix:** Follow Step 2 above to trust it in your browser.
onfig has `lum_hostname: "myserver.local"`, but you're accessing via IP `https://192.168.1.100:7993`

**Fix Option 1 - Update config and regenerate:**
```bash
# Edit data/loominum/config.json, change lum_hostname to the IP/hostname you're using
# Then regenerate certificate
./src/loominum/gencert.sh
# Re-trust the new certificate in your browser
```

**Fix Option 2 - Add additional SAN:**
```bash
# Keep current config, but add IP as additional SAN
./src/loominum/gencert.sh 192.168.1.100
# Re-trust the new certificate in your browser
```

**Verify certificate SANs:**
```bash
openssl x509 -in src/loominum/certs/cert.pem -text -noout | grep -A1 "Subject Alternative Name"
```

Should show: `DNS:localhost, IP:127.0.0.1, DNS:myserver.local` (or your configured hostname
openssl x509 -in src/loominum/certs/cert.pem -text -noout | grep -A1 "Subject Alternative Name"
```

Should show: `DNS:localhost, IP:127.0.0.1, IP:192.168.1.100` (or whatever you added)

### Certificate not being used

Check that the cert files exist:
```bash
ls -la src/loominum/certs/
```

Should show:
```
cert.pem
key.pem
```

### Mixed content warnings

If loading the page over http:// but trying to connect with wss://, you'll get mixed content errors. Ensure you're loading the page itself over https://.

### Certificate expired

Self-signed certs expire (default 365 days). Re-run `util/gencert.py --force` to create a new one, then re-trust it in your browser.

## Security Notes

- **Local use only:** Self-signed certificates should only be used for localhost/development
- **Don't share the private key:** Keep `key.pem` secure
- **Regenerate periodically:** Certificates expire after 365 days
- **For production:** Use Let's Encrypt or other trusted CA
fig to use http (optional - will fallback to http:// without cert anyway)
# Edit data/loominum/config.json:
#   "lum_hostname": "localhost"

# Restart server (will use http:// without SSL)
python src/loominum/server.py
```

## Configuration Reference

**data/loominum/config.json:**
```json
{
  "lum_hostname": "localhost",  // Hostname/IP for browser connections
  // Set to "myserver.local" for hostname
  // Set to "192.168.1.100" for IP address
  // ... other config fields
}
```

The `lum_hostname` value affects:
- Browser connection URL (shown in server startup)
- SSL certificate CN (Common Name)
- SSL certificate SAN (always includes hostname + localhost + 127.0.0.1)
- WebSocket connection endpointemove certificate files
rm -rf src/loominum/certs/

# Update connection URL
# Edit src/loominum/common.py:
CLIENT_CONNECTION_URL = 'http://localhost:7993'

# Restart server (will use http:// without SSL)
python src/loominum/server.py
```
