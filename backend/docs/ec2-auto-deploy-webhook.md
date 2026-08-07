# EC2 Auto Deploy Webhook (for GitHub Actions)

On push to `main`, `.github/workflows/backend-ci-cd.yml`:

1. runs the evals
2. builds and pushes the image to GHCR
3. if `BACKEND_DEPLOY_WEBHOOK_URL` is set, calls it with
   `POST` + header `X-Deploy-Token: <BACKEND_DEPLOY_WEBHOOK_SECRET>`

The receiver is `deploy/webhook/kiwi_deploy_webhook.py`, run by
`deploy/systemd/kiwi-deploy-webhook.service` and reverse-proxied by
`deploy/nginx/api.conf` at `/deploy`.

## Required GitHub secrets

| Secret | Purpose |
| --- | --- |
| `BACKEND_DEPLOY_WEBHOOK_URL` | e.g. `https://api.kiwiai.shivamio.in/deploy`. Unset = skip deploy, image still published. |
| `BACKEND_DEPLOY_WEBHOOK_SECRET` | Must equal `DEPLOY_WEBHOOK_SECRET` in `/opt/kiwi/webhook.env`. |

## Layout on EC2

```
/opt/kiwi/
  docker-compose.ec2.yml     # from deploy/
  backend.env                # from deploy/backend.env.example
  webhook.env                # from deploy/webhook.env.example  (hand-maintained)
  scripts/sync-deploy-assets.sh
  scripts/docker-disk-cleanup.sh
  webhook/kiwi_deploy_webhook.py
  src/                       # shallow clone, created by the sync
```

`webhook.env` must define `BACKEND_IMAGE` — `docker-compose.ec2.yml` declares
`image: ${BACKEND_IMAGE:?...}`, so `docker compose pull` exits non-zero without it.

## Host asset sync (push-to-deploy for `deploy/`)

The Docker image is built from `./backend`, so nothing under `deploy/` ships in
it. Those files run on the host: the webhook service, the compose file, nginx.

Set `DEPLOY_REPO_URL` in `webhook.env` and the webhook refreshes them from git
at the start of every deploy, before pulling the image. A push to `main` then
updates the app *and* the infrastructure around it, with no SSH.

```bash
DEPLOY_REPO_URL=https://github.com/OWNER/REPO.git   # private: https://USER:PAT@github.com/...
DEPLOY_REPO_BRANCH=main
DEPLOY_SYNC_NGINX=0
```

What it syncs into `/opt/kiwi`: `docker-compose.ec2.yml`, `prometheus.yml`,
`grafana-provisioning/`, `scripts/`, `webhook/`, plus the systemd unit.
`backend.env` and `webhook.env` are never touched — they hold secrets.

When the webhook's own source changes it cannot swap its code mid-request, so it
answers first and then exits; `Restart=always` brings it back on the new code.
The response reports this as `"webhook_restarting": true`.

`DEPLOY_SYNC_NGINX=1` additionally overwrites installed site configs from
`deploy/nginx/`. Off by default because certbot rewrites those files, and a bad
config takes the API and preview domains down. The sync only touches sites that
already exist, runs `nginx -t`, and restores the previous copies if the test
fails.

A sync failure never blocks the deploy — the image still gets pulled, and the
response carries `sync.status` so you can see what happened.

### Turning it on

Once, from a checkout on the instance:

```bash
sudo DEPLOY_REPO_URL=https://github.com/OWNER/REPO.git \
  bash deploy/scripts/bootstrap-ec2.sh
```

That installs the assets, records `DEPLOY_REPO_URL`, restarts the service and
runs preflight. After it succeeds, pushes are self-applying.

**Security note:** the webhook runs as root, so anyone who can push to `main`
can change files on the host through this. That is already broadly true via the
image, but the sync makes it direct. Keep `main` protected, and leave
`DEPLOY_REPO_URL` unset if you would rather copy `deploy/` by hand.

## GHCR authentication

**Packages published by GitHub Actions are private by default.** An
unauthenticated `docker compose pull` then fails with `denied` or
`unauthorized`, and the webhook reports it as step `compose_pull`.

Pick one:

- Make the package public: GitHub > your profile > Packages >
  `kiwi-ai-backend` > Package settings > Change visibility.
- Or set `GHCR_USERNAME` and `GHCR_TOKEN` (a PAT with `read:packages`) in
  `/opt/kiwi/webhook.env`. The webhook runs `docker login ghcr.io` before
  pulling when both are present.

## Diagnosing a failed deploy

The webhook answers with JSON naming the failing step and a hint, and the
workflow prints that body. Common responses:

| step | Meaning |
| --- | --- |
| `preflight:env_file` | `/opt/kiwi/webhook.env` missing |
| `preflight:backend_image` | `BACKEND_IMAGE` not set in `webhook.env` |
| `preflight:disk` | Still under 2 GB free after pruning |
| `ghcr_login` | `GHCR_USERNAME` / `GHCR_TOKEN` rejected |
| `compose_pull` | Pull failed — usually private-package `denied` |
| `compose_up` | Image pulled but the container would not start |

`sync.status` is reported separately, since a sync problem does not fail the
deploy: `ok`, `disabled` (no `DEPLOY_REPO_URL`), `missing` (script not installed),
or `failed` (clone/fetch problem — check the URL and repo visibility).

A `docker login` as `ubuntu` does nothing for the webhook: credentials live in
`~/.docker/config.json` per user, and systemd runs this service as root. Use
`GHCR_USERNAME` / `GHCR_TOKEN`, or make the package public.

Check config without deploying (same token as `/deploy`):

```bash
curl -s -H "X-Deploy-Token: $DEPLOY_WEBHOOK_SECRET" \
  https://api.kiwiai.shivamio.in/deploy-health | jq
```

On the instance:

```bash
sudo journalctl -u kiwi-deploy-webhook -n 100 --no-pager
cd /opt/kiwi && docker compose --env-file webhook.env -f docker-compose.ec2.yml pull backend
```

Note: `webhook.env` is loaded by systemd at service start, so run
`sudo systemctl restart kiwi-deploy-webhook` after editing it. Preflight reads
the file directly, so `/deploy-health` reflects edits immediately — a mismatch
between the two means a restart is pending.

## Backend container environment

Set in `/opt/kiwi/backend.env` (see `deploy/backend.env.example`):
`DATABASE_URL`, `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), `CLERK_JWKS_URL`,
`CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, `CORS_ORIGINS`,
`ENVIRONMENT=production`, `FINANCE_ENABLED=false`, and
`PREVIEW_ALLOWED_HOSTS` (the live-preview host allowlist).
