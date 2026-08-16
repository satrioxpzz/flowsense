# FlowSense

Edge vehicle detection for Kudus CCTV streams. Reads an HLS feed, runs
YOLOv11, maps detections into per-lane ROIs, and emits tiny metadata JSON
(kilobytes, not video). Optionally uses YOLO tracking to count each vehicle
once per lane crossing.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env     # then fill in FLOWSENSE_API_KEY
```

> Python 3.13 is required (the Docker image and the CUDA/PyTorch wheels are
> pinned to 3.13). See `pyproject.toml` for the installable package metadata.

## Components

FlowSense is more than the edge connector — it has four main pieces:

- **Edge connector** (`connector.py` → `flowsense/runner.py`): reads an HLS feed,
  runs YOLOv11, maps detections into per-lane ROIs, and emits tiny metadata JSON
  (`data/connector_<camera_id>.jsonl`). Supports YOLO tracking for unique
  lane-crossing counts.
- **FastAPI backend** (`flowsense/api_server/`): async SQLAlchemy + PostGIS
  storage of detections/alerts/cameras/intersections, with an X-API-Key-protected
  write surface and open read endpoints. Analytics aggregation at `/api/v1/analytics`.
- **SUMO simulation** (`flowsense/simulation/`): adaptive traffic-signal control
  driven by the edge counts, plus a performance analyzer. Run with
  `python -m flowsense.simulation --adaptive --duration 600`.
- **GarageHQ storage** (`flowsense/storage/`): S3-compatible off-site sync of
  detection JSONL and config files.

## Architecture

```
 Kudus CCTV (HLS)                 FlowSense edge                        FlowSense backend
 ┌──────────────┐   HLS feed    ┌────────────────────┐   JSONL/HTTP   ┌──────────────────────┐
 │ CCTV camera  │ ───────────▶ │ flowsense/runner.py │ ────────────▶  │ FastAPI (api_server) │
 │ (Pemkab     │               │  YOLOv11 + lanes   │   (X-API-Key)  │  PostgreSQL+PostGIS  │
 │  Kudus)     │               │  tracking + JSONL  │                │  Alembic migrations  │
 └──────────────┘               └─────────┬──────────┘                └──────────┬───────────┘
                                             │ failover queue                    │
                                             ▼                                   ▼
                                      ┌──────────────┐                 ┌──────────────────┐
                                      │ GarageHQ     │ ◀── sync ────── │ GarageHQ (S3)    │
                                      │ (off-site)   │                 └──────────────────┘
                                      └──────────────┘
```

The edge connector is designed to run on a GPU box near the camera. It can
operate fully offline: if the backend is unreachable, records are queued
locally (`data/sync/`) and flushed when connectivity returns (see
`flowsense/edge/failover.py`).

## Run the backend (FastAPI)

```bash
pip install -r requirements-api.txt
uvicorn flowsense.api_server.main:app --host 0.0.0.0 --port 8000
# requires Postgres/PostGIS up (see docker-compose.yml)
```

### Database & migrations

The backend needs a PostGIS database. Bring one up (or use `docker compose`),
set `DATABASE_URL`, then apply migrations:

```bash
# DATABASE_URL example (asyncpg + PostGIS):
export DATABASE_URL="postgresql+asyncpg://flowsense:flowsense@localhost:5432/flowsense"

# Create tables / apply schema changes:
alembic upgrade head
```

> The API does **not** auto-create tables on startup — run `alembic upgrade head`
> once after standing up the database. Migration scripts live in `migrations/`.

### API surface

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/health/` | open | Liveness/health check |
| GET | `/api/v1/detections/` | open | List detections (paginated: `limit`/`offset`) |
| POST | `/api/v1/detections/` | **X-API-Key** | Ingest a detection record |
| GET | `/api/v1/cameras/` | open | List cameras (paginated) |
| POST/PUT/DELETE | `/api/v1/cameras/` | **X-API-Key** | Manage cameras |
| GET | `/api/v1/intersections/` | open | List intersections |
| GET | `/api/v1/alerts/` | open | List alerts (paginated) |
| POST/PATCH | `/api/v1/alerts/` | **X-API-Key** | Create / acknowledge alerts |
| GET | `/api/v1/analytics/` | open | Aggregated traffic analytics |

Write endpoints require `X-API-Key` matching `FLOWSENSE_INBOUND_API_KEY`
(falls back to `FLOWSENSE_API_KEY`). Without a valid key they return **403**.
Read endpoints are intentionally public (no PII, aggregates only).

### Configuration (backend env)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | *(none)* | Async SQLAlchemy URL (asyncpg + PostGIS) |
| `FLOWSENSE_INBOUND_API_KEY` | *(none)* | Key the edge must send to write (fallback: `FLOWSENSE_API_KEY`) |
| `FLOWSENSE_CORS_ORIGINS` | *(empty)* | Comma-separated allowed CORS origins; empty disables CORS |
| `GARAGE_ENDPOINT` | `http://garage:3900` | GarageHQ S3 endpoint (inside compose network) |

## Run the SUMO simulation

```bash
export SUMO_HOME=$(python -c "import sumolib,os;print(os.path.dirname(sumolib.__file__))")
python -m flowsense.simulation --adaptive --duration 600      # adaptive signals
python -m flowsense.simulation --fixed    --duration 600      # read-only overlay
```

Useful flags:

- `--duration N` — simulation seconds (default 3600). Works for short runs too
  (≥ a few seconds; emergency-vehicle spawns are skipped below ~120 s).
- `--fast` — headless, faster step (skips slow GUI/trace output).
- `--lefthand` — Indonesia drives on the left; the generator already sets this.

Results are written to `output/` and summarized by the built-in analyzer
(`output/summary/report_*.md` + `.json`).

## GarageHQ off-site storage

`flowsense/storage/` syncs local files (detection JSONL, configs) to an
S3-compatible GarageHQ bucket. Configure via `config/garage.toml`:

```toml
region = "garage"
access_key = "..."
secret_key = "..."
# rpc_secret + rpc_bind_addr are required and must NOT be committed.
```

Then run a sync cycle:

```bash
python -m flowsense.storage.sync    # one-shot upload of closed/config files
```

The sync only uploads *closed* files (it skips files still being written, and
rotates daily `connector_*.jsonl` → `connector_*.YYYY-MM-DD.jsonl`) so a live
multi-GB file is never re-uploaded in full every cycle.

## Docker

`docker-compose.yml` brings up Postgres/PostGIS, GarageHQ, and the API
(with a healthcheck so the API waits for Postgres to be ready):

```bash
docker compose up --build
```

Notes:
- The API image is built from `Dockerfile` using `requirements-api.txt`.
- Postgres exposes `5432`; the API connects via `DATABASE_URL` (set in `.env`).
- Local `./data` is mounted into the container at `/app/data` so detection
  output persists across restarts.
- Apply migrations inside the API container once it is up:
  `docker compose exec api alembic upgrade head`.

## Calibrate lane ROIs

Draw per-lane polygons on a frame; saved to `config/rois.json`.

```bash
python calibrate.py --camera-id 30 --lanes "kota,ploso,demak,sekoe"
```

ROI coordinates are calibrated in the camera's native resolution
(`_resolution` is recorded on save). Run this before relying on per-lane counts.

## Run the connector

```bash
python connector.py --camera "Simpang DPRD Arah Kota"          # by name
python connector.py --camera-id 30                             # by id
python connector.py --url <m3u8> --out data/custom.jsonl       # direct URL
python connector.py --camera-id 30 --track                     # unique lane crossings
python connector.py --camera-id 30 --snapshot-only             # one frame, then exit
python connector.py --camera-id 30 --skip-detect               # stream check, no model
python -m flowsense --camera-id 30                             # module entry point
```

### Output

One JSON object per line in `data/connector_<camera_id>.jsonl`:

```json
{"ts":1755000000,"camera_id":30,"camera":"...","total_vehicles":4,"per_lane":{"kota":2}}
```

With `--track`, records also include cumulative `crossings`:

```json
{"ts":1755000000,"camera_id":30,"camera":"...","total_vehicles":2,"per_lane":{"kota":1},"crossings":{"kota":12}}
```

## Configuration (edge env / .env)

The edge connector reads these from `.env` (or the environment):

| Variable | Default | Meaning |
|---|---|---|
| `FLOWSENSE_API_KEY` | *(none)* | Kudus CCTV API key (required) |
| `FLOWSENSE_API_URL` | `https://kudussehat.kuduskab.go.id/api/get-cctv` | Camera list endpoint |
| `FLOWSENSE_API_TIMEOUT` | `25` | API request timeout (s) |
| `FLOWSENSE_API_RETRIES` | `3` | API retries before giving up |
| `FLOWSENSE_API_BACKOFF` | `2` | Base backoff (s), doubled per retry |
| `FLOWSENSE_MIN_CONF` | `0.35` | Min YOLO confidence for vehicles |
| `FLOWSENSE_INTERVAL` | `2` | Seconds between metadata records |
| `FLOWSENSE_MODEL` | `yolo11n.pt` | YOLO weights path |

## Development

```bash
# Install everything (edge + api + dev tools)
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .                       # install the 'flowsense' package

# Lint / format (config: ruff.toml)
ruff check .
ruff format --check .

# Tests (CI also runs these on every push)
python -m pytest -q
```

Conventions:
- New backend models inherit from `Base` in `flowsense/database/database.py`
  and get async routes under `flowsense/api_server/routes/`.
- Database changes go through Alembic migrations (`migrations/versions/`),
  never raw `create_all`.
- Keep `.env`, secrets, and real CCTV credentials out of git.

## Tests

```bash
python -m pytest -q
```

No network or camera access is needed; stream and API code are tested with fakes
(`tests/` has focused suites for detector, adapter, algorithm, controller,
generator, analyzer, routes auth, and the edge failover/queue logic).

## License

MIT — see [LICENSE](./LICENSE).
