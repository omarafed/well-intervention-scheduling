# Dedicated-server staging deployment

The repository-root `.github/workflows/build-images.yml` builds and deploys the
`revamped/` application when a `stag-*` tag is pushed. A manual run from the
Actions tab also deploys staging. It follows EDAFY's GHCR/SSH deployment pattern.
It does not deploy the original notebook or publish the frontend to Cloudflare Pages.

## One-time GitHub setup

In **this repository**, create **Settings → Environments → staging**. Copy the
values of these environment secrets from `edafy-asset`'s **staging** environment:

| Secret | Purpose |
| --- | --- |
| `DEPLOY_HOST` | Same dedicated staging server hostname or IP |
| `DEPLOY_USER` | Same SSH user, with Docker access and write access to `/opt/bayu-platform/staging` |
| `DEPLOY_SSH_KEY` | Same private SSH key already authorized on that server |
| `DEPLOY_PORT` | Optional SSH port; defaults to `22` |
| `DEPLOY_HOST_FINGERPRINT` | Optional SSH host SHA256 fingerprint, used by both SSH and SCP |

Secrets in another repository's GitHub Environment are not inherited. Copy their
values from your secret manager, or grant this repository access to equivalent
organization secrets. GitHub cannot reveal an existing secret's plaintext.
The workflow validates the three required secrets before building.

GHCR authentication uses the built-in `GITHUB_TOKEN`; no separate registry PAT
is required. Images published by this workflow must retain Actions access for
this repository. The workflow builds Linux AMD64 images, matching the reference
deployment; the server must support that architecture.

Optional **staging environment variables**:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_PORT` | `3010` | Host port for the Nuxt frontend |
| `API_PORT` | `8090` | Host port for the Go API |
| `BIND_ADDRESS` | `0.0.0.0` | Use `127.0.0.1` when routing through a host reverse proxy or tunnel |
| `PUBLIC_APP_URL` | `http://<DEPLOY_HOST>:3010` | Exact browser origin, without a trailing slash; also configures CORS |
| `PUBLIC_API_BASE` | `http://<DEPLOY_HOST>:8090/api` | Browser API URL, ending in `/api` |

Default URLs follow any overridden ports. For an HTTPS deployment, configure
both public URLs with HTTPS, and route them to the corresponding local ports
through your existing reverse proxy or Cloudflare Tunnel. With a tunnel, set
`BIND_ADDRESS=127.0.0.1` and run the tunnel connector on the server host. CORS
permits the configured frontend origin; use that URL to access the application.

## Server layout

The server already hosting EDAFY needs Docker Compose supporting multiple
`--env-file` flags and `up --wait --wait-timeout`, plus Bash, OpenSSL, curl and
`flock` (normally supplied by util-linux on Linux). No Docker installation or
upgrade is performed by the workflow.

For a non-root deployment user, provision the app's directory once:

```bash
sudo mkdir -p /opt/bayu-platform/staging
sudo chown "$USER" /opt/bayu-platform/staging
```

Files live in `/opt/bayu-platform/staging`:

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

Open **Actions → Build & Deploy Platform Images**. The workflow:

1. Validates the staging secrets and resolves a release tag including the commit
   SHA, run ID and attempt, so reruns do not overwrite another run's images.
2. Runs Go tests/vet, optimizer tests, deployment-script tests and Compose validation.
3. Builds and pushes backend, frontend, optimizer and MinIO images to GHCR.
   The worker runs the backend image with its `worker` command.
4. Copies the staging configuration into a run-specific temporary directory and
   invokes the deployment script over SSH.
5. Preserves service credentials, pulls all images before restarting anything,
   and waits for healthy containers and successful API/frontend HTTP responses.

Default addresses are `http://<server>:3010` and `http://<server>:8090/api`.
Configured ports must be free and allowed by your network/firewall when accessed
directly. The app remains a shared workspace without login; anyone who can reach
its API can read and edit its data.

## Recovery and verification

On the server:

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
`stag-*` tag pointing to that commit. Database schema compatibility must be
considered when deploying older code because startup uses GORM AutoMigrate.
Back up PostgreSQL, imported files and `.env.prod` separately.

Local configuration/script checks:

```bash
bash -n revamped/deploy/staging.sh
python3 -m unittest discover -s revamped/deploy -v
```

A real GitHub-to-server run requires the configured environment secrets; local
validation cannot verify those credentials or the dedicated server's port availability.
