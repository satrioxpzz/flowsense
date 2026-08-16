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

## Run the backend (FastAPI)

```bash
pip install -r requirements-api.txt
uvicorn flowsense.api_server.main:app --host 0.0.0.0 --port 8000
# requires Postgres/PostGIS up (see docker-compose.yml)
```

## Run the SUMO simulation

```bash
export SUMO_HOME=$(python -c "import sumolib,os;print(os.path.dirname(sumolib.__file__))")
python -m flowsense.simulation --adaptive --duration 600      # adaptive signals
python -m flowsense.simulation --fixed    --duration 600      # read-only overlay
```

## Docker

`docker-compose.yml` brings up Postgres/PostGIS, GarageHQ, and the API:

```bash
docker compose up --build
```

## Calibrate lane ROIs

Draw per-lane polygons on a frame; saved to `config/rois.json`.

```bash
python calibrate.py --camera-id 30 --lanes "kota,ploso,demak,sekoe"
```

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

## Configuration (env / .env)

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

## Tests

```bash
python -m pytest -q
```

No network or camera access is needed; stream and API code are tested with fakes.
