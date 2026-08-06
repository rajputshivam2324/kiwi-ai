# EC2 Reverse Proxy for Live Vite Previews

This project starts the Vite dev server for previews on the backend machine (by spawning `npm run dev`).

To avoid exposing dynamic preview ports to the public internet, you can proxy a dedicated subdomain (recommended) to the fixed preview port.

## Preconditions

1. Set `BUILDER_MAX_LIVE_PREVIEWS=1` on the backend.
   - The backend now keeps Vite on a fixed port (`PREVIEW_PORT_START`, default `5200`) when only 1 live preview is allowed.
2. Configure Vite preview access:
   - In the frontend, set `VITE_PREVIEW_BASE_URL=https://preview.<your-domain>` (or whatever hostname you use).

## DNS

Point this record to your EC2 public IP:

- `preview.<your-domain>` → EC2

## Nginx config (example)

Assuming your preview host is `preview.<your-domain>` and Vite listens on `127.0.0.1:5200`:

```nginx
server {
  listen 443 ssl http2;
  server_name preview.<your-domain>;

  # Put your cert/key paths here (e.g. from certbot)
  ssl_certificate     /etc/letsencrypt/live/preview.<your-domain>/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/preview.<your-domain>/privkey.pem;

  location / {
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;

    proxy_read_timeout 3600;
    proxy_send_timeout 3600;

    proxy_pass http://127.0.0.1:5200;
  }
}
```

## Verify

1. Open `https://preview.<your-domain>` in a browser.
2. Start a Builder preview and confirm the iframe loads successfully.

## Why a subdomain

Vite dev server asset paths (like `/@vite/client`) assume serving from `/`.
Proxing it under a sub-path like `/preview/` often breaks asset loading.
Using a dedicated host avoids this issue.

