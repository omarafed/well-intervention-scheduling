# Dedicated-server deployment

The repository-root `.github/workflows/build-images.yml` builds and deploys the
`revamped/` application when a `stag-*` tag is pushed. A manual run from the
Actions tab also deploys staging.
`.github/workflows/deploy-development.yml` does the same for `dev-*` tags and
manual development runs, using the `development` GitHub environment. It follows EDAFY's GHCR/SSH deployment pattern.
It does not deploy the original notebook or publish the frontend to Cloudflare Pages.

## One-time GitHub setup

In **this repository**, create **Settings → Environments → staging** and
**development**. Configure `DEPLOY_HOST` separately in each environment, using
its server hostname or IP (without a URL scheme or path).

Under **Settings → Secrets and variables → Actions → Repository secrets**, add
`DEPLOY_USER` and `DEPLOY_SSH_KEY` once. Both workflows use these shared SSH
credentials. The same user and key must be authorized on both target servers.
Leave these two secrets unset at environment level so they use the repository
values; environment secrets with the same names take precedence.

| Secret | Scope | Purpose |
| --- | --- | --- |
| `DEPLOY_HOST` | Each environment | That environment's dedicated server hostname or IP |
| `DEPLOY_USER` | Repository | Shared SSH user with Docker access and write access to each deployment directory |
| `DEPLOY_SSH_KEY` | Repository | Shared private SSH key authorized on both servers |
| `DEPLOY_PORT` | Repository or environment | Optional SSH port; defaults to `22` |
| `DEPLOY_HOST_FINGERPRINT` | Each environment | Optional SSH host SHA256 fingerprint, used by both SSH and SCP |

Secrets in another repository's GitHub Environment are not inherited. Copy their
values from your secret manager, or grant this repository access to equivalent
organization secrets. GitHub cannot reveal an existing secret's plaintext.
The workflow validates the three required secrets before building.

GHCR authentication uses the built-in `GITHUB_TOKEN`; no separate registry PAT
is required. Images published by this workflow must retain Actions access for
this repository. The workflow builds Linux AMD64 images, matching the reference
deployment; the server must support that architecture.

Optional **environment variables**, configured separately in `staging` and
`development`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_PORT` | `3010` | Host port for the Nuxt frontend |
| `API_PORT` | `8090` | Host port for the Go API |
| `BIND_ADDRESS` | `0.0.0.0` | Use `127.0.0.1` when routing through a host reverse proxy or tunnel |
| `PUBLIC_APP_URL` | `http://<DEPLOY_HOST>:3010` | Exact browser origin, without a trailing slash; also configures CORS |
| `PUBLIC_API_BASE` | `http://<DEPLOY_HOST>:8090/api` | Browser API URL, ending in `/api` |

Both server workflows set `APP_BASE_PATH=/bayu/rig/`. Frontend links include
that path; `PUBLIC_APP_URL` remains the origin only for CORS. Local Compose
continues to default to `/`.

Default URLs follow any overridden ports. For an HTTPS deployment, configure
both public URLs with HTTPS, and route them to the corresponding local ports
through your existing reverse proxy or Cloudflare Tunnel. With a tunnel, set
`BIND_ADDRESS=127.0.0.1` and run the tunnel connector on the server host. CORS
permits the configured frontend origin; use that URL to access the application.

## Server layout

Each target server needs Docker Compose supporting multiple
`--env-file` flags and `up --wait --wait-timeout`, plus Bash, OpenSSL, curl and
`flock` (normally supplied by util-linux on Linux). No Docker installation or
upgrade is performed by the workflow.

For a non-root deployment user, provision the app's directory once:

```bash
sudo mkdir -p /opt/bayu-platform/staging
sudo chown "$USER" /opt/bayu-platform/staging
```

For development, provision `/opt/bayu-platform/development` instead. Its workflow
sets Compose project `bayu-platform-development`, isolating its network and volumes.
Both environments use the same Compose file and deployment script. If deploying
both to the same server, assign distinct `APP_PORT` and `API_PORT` values.

Files live in `/opt/bayu-platform/staging` (or `/opt/bayu-platform/development`):

- `compose.staging.yaml`: image-based server configuration.
- `.env.prod`: generated database, internal-service and MinIO credentials, mode
  `600`. Created only on the first deployment and retained on later deployments.
- `.env.release`: image tag and browser URL/port settings from the last successful
  deployment, mode `600`. Preserve this file for manual recovery.

Compose project `bayu-platform-staging` gives the app its own network and
PostgreSQL/Redis/MinIO volumes. No fixed container names are used. Default host
ports differ from EDAFY's `3000` frontend and `8085` API. PostgreSQL, Redis, MinIO
and the Python optimizer are not published on host ports. Existing EDAFY data
and the `/opt/edafy/run` deployment directory are not used. Local app data is not
automatically migrated to the server's fresh workspace.

## Deploy

First commit and push the workflow, Compose file, and deployment script. Then tag
that commit, using a new tag name for each release:

```bash
git tag stag-2026.10.09-1
git push origin stag-2026.10.09-1
```

For development, use a `dev-*` tag instead:

```bash
git tag dev-2026.10.27-1
git push origin dev-2026.10.27-1
```

Open **Actions → Build & Deploy Platform Images** for staging or
**Build & Deploy Development Images** for development. Each workflow:

1. Validates its environment secrets and resolves a release tag including the commit
   SHA, run ID and attempt, so reruns do not overwrite another run's images.
2. Runs Go tests/vet, optimizer tests, deployment-script tests and Compose validation.
3. Builds and pushes backend, frontend, optimizer and MinIO images to GHCR.
   The worker runs the backend image with its `worker` command.
4. Copies the deployment configuration into a run-specific temporary directory and
   invokes the deployment script over SSH.
5. Preserves service credentials, pulls all images before restarting anything,
   and waits for healthy containers and successful API/frontend HTTP responses.

Default addresses are `http://<server>:3010/bayu/rig/` and `http://<server>:8090/api`.
Configured ports must be free and allowed by your network/firewall when accessed
directly. The app remains a shared workspace without login; anyone who can reach
its API can read and edit its data.

## Recovery and verification

On the staging server (for development, substitute directory
`/opt/bayu-platform/development` and project `bayu-platform-development`):

```bash
cd /opt/bayu-platform/staging
docker compose --project-name bayu-platform-staging \
  --env-file .env.prod --env-file .env.release -f compose.staging.yaml ps
```

The workflow never runs `compose down`, removes volumes, or prunes shared server
images. Failed pulls leave running containers untouched. If a new release becomes
unhealthy, the workflow fails and prints application logs; it does not claim to
roll back partially updated containers. Fix the problem and rerun. To redeploy a
known commit, run this workflow on its existing `stag-*` tag, or push a new
`stag-*` tag pointing to that commit. For development, use its workflow and
`dev-*` tags instead. Database schema compatibility must be
considered when deploying older code because startup uses GORM AutoMigrate.
Back up PostgreSQL, imported files and `.env.prod` separately.

Local configuration/script checks:

```bash
bash -n revamped/deploy/staging.sh
python3 -m unittest discover -s revamped/deploy -v
```

A real GitHub-to-server run requires the configured environment secrets; local
validation cannot verify those credentials or the dedicated server's port availability.

## Shared staging server resource budget

The server profile targets the shared 2-vCPU / 4-GiB host. Docker limits the
whole Bayu stack to a combined 1.5 CPU cores and 2 GiB RAM, leaving at least
0.5 CPU cores and 2 GiB outside these container budgets for the OS and other
applications. These are ceilings, not reservations; existing applications may
already need more than the remaining capacity. Development uses this same profile.
Running both projects on one host doubles their combined budgets.

| Service | CPU cores | RAM ceiling |
| --- | ---: | ---: |
| Optimizer | 0.50 | 768 MiB |
| PostgreSQL | 0.20 | 256 MiB |
| Redis | 0.10 | 128 MiB |
| MinIO | 0.20 | 384 MiB |
| API | 0.15 | 128 MiB |
| Queue worker | 0.15 | 128 MiB |
| Frontend | 0.20 | 256 MiB |

The optimizer uses one Uvicorn process, one CP-SAT search worker, and one
native math thread. A process-wide guard admits only one solve at a time,
including the model build and final result calculation. Extra synchronous
requests receive HTTP 503; streaming requests receive a retryable error. The
queue worker already processes one job at a time. Keep a single optimizer
replica: its guard is process-local. Disconnects signal cancellation during
model building and search; the slot remains occupied until the solve exits.

Models requiring more than 20,000 directed well-to-well connections across
compatible platforms are rejected before model allocation. For example,
100 active wells compatible with each of three platforms require 29,700
connections, so that request must be split. Dropped and incompatible wells
are excluded from this count. This is a conservative complexity guard, not
a measured guarantee of peak memory. Distances are cached across platforms
and previews are built at most once per second. The objective and routing
constraints remain unchanged. One search worker and a half-core quota can
find fewer improvements within the existing 45-second search limit.

PostgreSQL uses 64 MiB shared buffers, 2 MiB work memory and 30 connections
(the API and queue worker each allow 10). Redis rejects new writes at its
64 MiB dataset limit rather than evicting queued jobs; monitor queue growth.
Memory plus swap ceilings equal RAM ceilings, so these containers cannot
consume host swap. Go services use one scheduler CPU and a 96 MiB soft Go
memory target. Compose pulls and starts services serially to reduce deployment
bursts; image extraction still uses host Docker resources outside container caps.

After deploying a new image release, inspect actual usage while running a
representative optimization:

```bash
cd /opt/bayu-platform/staging
docker compose --project-name bayu-platform-staging \
  --env-file .env.prod --env-file .env.release -f compose.staging.yaml ps -q | xargs docker stats --no-stream
free -h
uptime
sudo journalctl -k --since '1 hour ago' | grep -Ei 'oom|out of memory|killed process'
```

An optimizer CPU reading around 50% in `docker stats` represents half of one
core, or 25% of this two-core host. If a container restarts, inspect its
`State.OOMKilled`, restart count and logs. A container exceeding its RAM cap
can still be killed; the cap protects the shared host. No server logs were
available during this change, so CPU oversubscription and unbounded model
memory are identified risks, not a confirmed diagnosis of the reported crash.

## Frontend reverse proxy at /bayu/rig/

Dev and staging both serve the frontend at `/bayu/rig/`. Nuxt receives
`NUXT_APP_BASE_URL=/bayu/rig/` in the frontend container at runtime; rebuilding
assets for each hostname is unnecessary. Both workflows pass this setting to
the deployment script, which saves it in `.env.release`. Container health checks
and deployment HTTP probes use this same path.

For development, set `PUBLIC_APP_URL=https://asset-dev.edafylabs.com` in the
GitHub environment, without the path or trailing slash. Use the staging origin
in the staging environment. Keep `PUBLIC_API_BASE` pointed at the actual backend
API endpoint, ending in `/api`; the frontend base path does not relocate the Go
backend routes.

On each server, configure the existing proxy to send the entire `/bayu/rig/`
prefix, including `/bayu/rig/_nuxt/`, to the Bayu frontend port (3010 by default).
For Nginx inside the existing domain's `server` block:

```nginx
location = /bayu/rig {
    return 308 /bayu/rig/;
}

location ^~ /bayu/rig/ {
    # No trailing slash: preserve /bayu/rig/ in the upstream request.
    proxy_pass http://127.0.0.1:3010;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

For a path-based tunnel route, use the equivalent path match and preserve the
prefix. Requests for these frontend assets must reach the frontend, rather than
the Go API or another Nuxt app. Avoid forwarding all domain-root `/_nuxt/`
requests to Bayu, since another app may own that path.

After redeploying and updating the proxy, open `/bayu/rig/` and check the Network
tab: CSS and JavaScript URLs should start with `/bayu/rig/_nuxt/`, return 200,
and have CSS/JavaScript content types. A JSON response to a stylesheet request
usually means an error handler or the wrong upstream answered. Changing MIME
headers would only disguise that failure. Purge any cached old HTML for this
app path and hard-refresh if it still references domain-root `/_nuxt/` assets.
