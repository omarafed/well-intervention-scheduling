# Bayu Platform Scheduling

A separate application built from the scheduling model in `../Trial.ipynb`. The original notebook remains usable. All new interfaces, models, imports, and schedule exports use **platform** terminology.

## Run locally

Install Docker with Compose, then from this folder:

```sh
docker compose up --build -d
docker compose logs -f api worker optimizer
```

Open **http://localhost:3000** to use the shared workspace immediately. The app is a single page: data and scenario controls sit on the left, with optimization progress and results on the right. Below 1024px, these columns stack. Well and platform management are collapsed by default; open their panels to add or edit records. Charts, risk analysis, the schedule, and scenario history are also collapsible. If the workspace is empty, click **Load demo data**. Run an optimization to see its results directly, or open a saved run under **Scenario history & imports**. Upload the files in `examples/` through **Import datasets**. Imports merge by name, update matching records, and validate the entire file before committing.

| Service | Local access |
| --- | --- |
| Nuxt frontend | http://localhost:3000 |
| Echo API | http://localhost:8080/api |
| API health | http://localhost:8080/health |
| MinIO console | http://localhost:9001 — `bayu` / `bayu-local-storage` |
| PostgreSQL, Redis, optimizer, MinIO S3 | Internal Compose network |

Optional: copy `.env.example` to `.env` before starting to override local defaults. Volumes preserve datasets, staged uploads, and queue data across restarts. `docker compose down` stops the services while retaining data. `docker compose down -v` deletes all local application data.

The first build needs internet access and takes several minutes. MinIO is built from a pinned upstream source release because its Community edition is now [distributed as source](https://github.com/minio/minio). The MinIO component retains its upstream AGPLv3 license.

## Architecture

```text
Nuxt 3 / Tailwind / Pinia / $fetch
          │
          ▼
Echo API / GORM ───────── PostgreSQL
          │                 ▲
          ├── MinIO          │ results + dataset imports
          │                 │
          └── Redis/Asynq → Go worker → Python/FastAPI/OR-Tools
```

The API serves one shared workspace without registration, login, or browser tokens. Everyone using this instance sees and edits the same wells, platforms, and scenarios. Optimization jobs store immutable input snapshots, so editing the dataset does not change an existing scenario. A Go Asynq worker calls the internal Python service, then persists the schedule and 10,000 Monte Carlo samples. Imports are staged in MinIO, parsed in Python (CSV/XLSX), validated, and upserted in a PostgreSQL transaction. The optimizer streams snapshots to the Go worker every five seconds, which saves progress and the best feasible schedule in PostgreSQL. The frontend polls every five seconds and refreshes the provisional timeline, routes, and totals when better solutions arrive. Both charts display a live snapshot timestamp and refresh independently of other page requests, including while the current best solution remains unchanged. A convergence chart shows the best score and solver upper bound; Monte Carlo charts and exports appear once the search completes.

Redis durably queues jobs using AOF. Completed job responses are cached briefly in Redis; PostgreSQL remains the source of truth. Workers run one job at a time to avoid oversubscribing the solver's four search threads. Transient failures retry twice; invalid input fails without retrying. Worker operations are idempotent on replay, and import transactions prevent partial datasets.

## Scheduling behavior

- Preserves the notebook's CP-SAT compatibility, routing, mobilization and cumulative production objective, with distance penalties.
- Planning horizon: 365 days from the chosen start date; solver search: up to 45 seconds.
- Progress reports elapsed time, improving solutions found, the best objective score and upper-bound gap. The bar measures the search time budget used, not the percentage of mathematical optimality. The solver can finish early. Updates continue every five seconds even when it has not found a new solution; the best existing preview remains visible.
- Preview schedules are feasible candidates, with the same compatibility and transit constraints as final schedules. A time-limited run may finish with FEASIBLE status rather than a proven optimum. Monte Carlo analysis runs once, after the search, instead of slowing every live preview.
- All non-excluded wells must be scheduled. Unsupported categories, excessive durations, or an infeasible configuration produce a failed job with an explanation.
- Transit uses the notebook's approximation: `ceil(distance_km / 50) + 1` days between consecutive wells.
- Daily cost is kUSD; mobilization days are included in each intervention's cost. Transit days are not charged, matching the notebook.
- Contract end dates are **advisory**, with result warnings; they are not hard scheduling constraints.
- Risk uses triangular duration factors 0.8 / 1.0 / 1.5 and gain factors 0.7 / 1.0 / 1.2. Gain P90 is the lower percentile; cost P90 is the upper percentile. Simulation is vectorized with a fixed seed, so exact random samples differ from the notebook while retaining its distributions.
- Limits: 200 wells / 20 platforms per optimization; 1,000 rows / 10 MiB per import. Larger workloads need profiling and resource limits.

The initial application supports dataset editing, excluded wells and saved scenario history. Manual schedule overrides, locked interventions, collaborative approval flows, and scenario comparison overlays are not implemented. The notebook accepted locked-well inputs but did not apply them in its optimization model, so the new app does not expose an ineffective lock control.

## API

All application API routes are accessible directly without an Authorization header. The optimizer remains an internal service with its own service token.

| Method | Route | Purpose |
| --- | --- | --- |
| GET / POST | `/api/wells`, `/api/platforms` | List / create records |
| PUT / DELETE | `/api/wells/:id`, `/api/platforms/:id` | Update / delete record |
| POST | `/api/imports/wells`, `/api/imports/platforms` | Multipart `file`; returns import job |
| POST | `/api/optimizations` | `{name, start_date, dropped_wells: []}`; returns scenario job |
| GET | `/api/jobs` | Latest 100 workspace jobs |
| GET | `/api/jobs/:id` | Job, saved inputs, progress, and provisional or final result |
| POST | `/api/demo` | Populate an empty workspace with sample data |

Platform import columns: `Platform_Name,Type,Supported_Job_Categories,Mob_Demob_Days,Daily_Cost_kUSD,Contract_End_Date`. The legacy `Rig_Name` header is also accepted when `Platform_Name` is absent, including the original `../example_rig.csv`; imported names are preserved as supplied. Use semicolons between categories, especially custom categories containing commas. Well import columns: `Well_ID,Job Category,Duration_Days,Gain_BOPD,Lat,Lon` (`BOPD` is also accepted). Templates are downloadable in the UI.

## Development and verification

```sh
cd backend
go test ./...
go vet ./...
cd ../frontend
npm ci
npm run build
cd ../optimizer
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests
```

After Compose is running, run the end-to-end smoke test from this folder:

```sh
python3 tests/smoke.py
```

It verifies direct access without credentials, creates uniquely named test wells and a platform, runs optimization, validates saved snapshots and risk results, and exercises staged CSV imports. It removes its test records afterward while preserving existing datasets. Saved test jobs remain visible in history.

For frontend development, run `npm run dev` in `frontend/` while the API is running. The frontend's public API base is configured with `NUXT_PUBLIC_API_BASE`.

## Hosting

Deploy the Nuxt frontend to Cloudflare using its supported Nuxt build preset or generate static assets with `npm run generate`. Set the public API base at build time for a static deployment. Run the Go API, worker, and Python optimizer on a container host near PostgreSQL and Redis. MinIO can be replaced with an S3-compatible service such as R2 by configuring `S3_ENDPOINT`, `S3_SECURE`, credentials and bucket; integration must be verified for that service.

Compose is a local development deployment with application ports bound to localhost. There is no application login: anyone who can reach the API can read and edit the shared workspace. Before public hosting, choose the intended network access boundary, replace service secrets, configure HTTPS and backups, and choose a production migration workflow. Startup currently uses GORM AutoMigrate. There is no claim of production hardening or a completed Cloudflare deployment.

Existing databases use workspace ID 1, preserving the first previous account's wells, platforms, and history. Other former account records and the old users table remain stored without being deleted or merged; the application no longer uses them. Fresh databases need no accounts. The legacy `user_id` database column now scopes the shared workspace internally.

## Verified locally

The Go tests and `go vet` pass. All optimizer tests pass both in the existing Python environment and inside the built optimizer container. The Nuxt production build succeeds. The API smoke test passes against all running Compose services, including direct unauthenticated access, CRUD, immutable scenario snapshots, optimization, Monte Carlo output, staged imports, and invalid-import rollback. A headless Chrome check opened the shared dashboard directly and verified rendering of all four result charts without browser errors.

The frontend dependency audit currently reports 20 upstream findings (6 critical, 10 high, 4 moderate), principally in Nuxt developer/build tooling and Tailwind's dependency chain. Devtools are disabled and the runtime Docker image contains only the generated Nuxt output. These findings are not resolved by this implementation and must be reviewed before public deployment; blindly applying the suggested Nuxt downgrade would conflict with the selected stack. Plotly's geography layer also fetches map topology from its public CDN, so map rendering needs internet access.
