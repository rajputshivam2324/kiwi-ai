# EC2 Auto Deploy Webhook (for GitHub Actions)

Your GitHub workflow `.github/workflows/backend-ci-cd.yml` triggers deploy like this:

- On push to `main`:
  - it builds + pushes the Docker image to GHCR
  - then (only if) `BACKEND_DEPLOY_WEBHOOK_URL` is set, it runs:
    - `POST $BACKEND_DEPLOY_WEBHOOK_URL`

So you need to provide that webhook endpoint on your EC2 setup.

## What you need on EC2

1. Docker installed and running
2. A place to store environment variables for the backend container (example: `/opt/kiwi/backend.env`)
3. A webhook receiver that accepts `POST` requests and performs:
   - `docker login ghcr.io`
   - `docker pull ghcr.io/<owner>/kiwi-ai-backend:latest`
   - stop + remove existing container
   - start new container with your env vars

## Environment variables you should provide to the backend container

At minimum (depending on your enabled modules):
- `DATABASE_URL`
- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
- `CLERK_JWKS_URL` / `CLERK_SECRET_KEY` / `CLERK_PUBLISHABLE_KEY`
- `CORS_ORIGINS=https://<your-vercel-domain>`
- `ENVIRONMENT=production`
- `FINANCE_ENABLED=false` (recommended unless you have MCP working properly)

## Webhook security

The workflow does `curl -fsSL -X POST` without an auth header.
To secure it, use one of:
- a random unguessable webhook URL (recommended simple approach)
- firewall restrict inbound to GitHub Actions IP ranges
- add an HTTP-level shared secret header (would require updating the workflow)

## Docker run target

Your backend container should expose `8000` to the internet (or be behind a reverse proxy).

Once you set `BACKEND_DEPLOY_WEBHOOK_URL` in GitHub, deployments become automatic: every push to `main` triggers the webhook, and EC2 restarts the container with the newly published image.

