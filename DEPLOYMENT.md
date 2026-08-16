# FlowSense Production Deployment Plan

**Status:** Ready for production deployment
**Date:** 2026-08-02
**Environment:** WSL2 / Linux (Python 3.13); the connector and API run under Linux, Docker Engine runs inside the WSL2 "Ubuntu" distro. The Windows host is only used for the terminal/git-bash wrapper.

---

## Pre-Deployment Checklist

✓ All 107 tests passing (see pytest; CI runs them on every push)
✓ API key configured in .env
✓ YOLO model (yolo11n.pt) downloaded
✓ ROIs calibrated for camera 30
✓ Snapshot test successful
✓ Structured JSON logging active
✓ Secrets moved to environment variables

---

## Deployment Options

### Option 1: Single Camera (Development/Testing)

Run one camera in foreground to verify everything works:

```bash
cd "$REPO_DIR"   # REPO_DIR = where you cloned FlowSense (e.g. /home/legion/flowsense on WSL)
python connector.py --camera-id 30
```

**Monitor:** Watch `data/connector_30.jsonl` for records every 2 seconds.

Press Ctrl+C to stop gracefully.

---

### Option 2: Single Camera as Background Service

Run one camera continuously in the background:

```bash
cd "$REPO_DIR"   # REPO_DIR = where you cloned FlowSense (e.g. /home/legion/flowsense on WSL)
nohup python connector.py --camera-id 30 > logs/camera_30.log 2>&1 &
```

**Monitor:**
- `tail -f logs/camera_30.log` (structured JSON logs)
- `tail -f data/connector_30.jsonl` (vehicle counts)

**Stop:**
```bash
pkill -f "connector.py --camera-id 30"
```

---

### Option 3: Multi-Camera Production Deployment

Run multiple cameras simultaneously, each tracking lane crossings:

```bash
cd "$REPO_DIR"   # REPO_DIR = where you cloned FlowSense (e.g. /home/legion/flowsense on WSL)

# Create logs directory
mkdir -p logs

# Start camera 30 (Simpang DPRD Arah Kota) with tracking
nohup python connector.py --camera-id 30 --track > logs/camera_30.log 2>&1 &

# Start camera 31 (if calibrated)
# nohup python connector.py --camera-id 31 --track > logs/camera_31.log 2>&1 &

# Start camera 32 (if calibrated)
# nohup python connector.py --camera-id 32 --track > logs/camera_32.log 2>&1 &
```

**Before starting additional cameras:**
1. Calibrate ROIs: `python calibrate.py --camera-id 31 --lanes "lane1,lane2"`
2. Test with snapshot: `python connector.py --camera-id 31 --snapshot-only`
3. Start in background

---

## Production Configuration

### Recommended .env settings for production:

```bash
FLOWSENSE_API_KEY=[REDACTED]   # real value goes in .env, never committed
FLOWSENSE_API_URL=https://kudussehat.kuduskab.go.id/api/get-cctv
FLOWSENSE_API_TIMEOUT=30           # increased for production
FLOWSENSE_API_RETRIES=5            # more retries
FLOWSENSE_API_BACKOFF=3            # longer backoff
FLOWSENSE_MIN_CONF=0.35            # tuned threshold
FLOWSENSE_INTERVAL=2               # 2-second intervals
FLOWSENSE_MODEL=yolo11n.pt         # lightweight model
```

---

## Monitoring & Operations

### Check if cameras are running:

```bash
ps aux | grep connector.py
```

### View live vehicle counts:

```bash
tail -f data/connector_30.jsonl
```

### View structured logs:

```bash
tail -f logs/camera_30.log | jq .
```

### Check for errors:

```bash
grep '"level":"ERROR"' logs/camera_30.log | jq .
```

### Restart a camera:

```bash
# Stop
pkill -f "connector.py --camera-id 30"

# Start
nohup python connector.py --camera-id 30 --track > logs/camera_30.log 2>&1 &
```

---

## Data Output

### Record Schema (without tracking):
```json
{
  "ts": 1785665649,
  "camera_id": "30",
  "camera": "Simpang DPRD Arah Kota",
  "total_vehicles": 4,
  "per_lane": {"kota": 2, "ploso": 1, "demak": 1}
}
```

### Record Schema (with --track):
```json
{
  "ts": 1785665649,
  "camera_id": "30",
  "camera": "Simpang DPRD Arah Kota",
  "total_vehicles": 4,
  "per_lane": {"kota": 2, "ploso": 1},
  "crossings": {"kota": 47, "ploso": 23, "demak": 15}
}
```

**Data location:** `data/connector_<camera_id>.jsonl`

---

## Troubleshooting

### Camera keeps reconnecting:
- Check stream URL is accessible
- Increase `FLOWSENSE_API_TIMEOUT`
- Check network connectivity

### No vehicles detected:
- Verify ROIs are calibrated: `ls -l config/rois.json`
- Lower `FLOWSENSE_MIN_CONF` (try 0.25)
- Test with `--snapshot-only` and check logs

### High CPU usage:
- Switch to `yolo11n.pt` (nano) model
- Increase `FLOWSENSE_INTERVAL` to 5 seconds
- Run fewer cameras per machine

### Memory leak:
- Restart cameras daily via cron:
```bash
0 3 * * * pkill -f connector.py && sleep 10 && /path/to/start_cameras.sh
```

---

## Backup & Maintenance

### Daily data backup:
```bash
# Backup data directory
tar -czf backups/flowsense-data-$(date +%Y%m%d).tar.gz data/

# Keep last 30 days
find backups/ -name "flowsense-data-*.tar.gz" -mtime +30 -delete
```

### Log rotation:
```bash
# Rotate logs weekly
find logs/ -name "camera_*.log" -size +100M -exec gzip {} \;
find logs/ -name "camera_*.log.gz" -mtime +90 -delete
```

---

## Next Steps

1. **Start with one camera** (Option 1) and verify output
2. **Monitor for 1 hour** - check logs, data quality, CPU usage
3. **Move to background** (Option 2) if stable
4. **Scale to multiple cameras** (Option 3) after calibrating ROIs
5. **Set up monitoring dashboard** - consume .jsonl files, visualize traffic

---

## Production Deployment Commands

### Quick Start (Single Camera):
```bash
cd "$REPO_DIR"   # REPO_DIR = where you cloned FlowSense (e.g. /home/legion/flowsense on WSL)
python connector.py --camera-id 30 --track
```

### Production Start (Background with logging):
```bash
cd "$REPO_DIR"   # REPO_DIR = where you cloned FlowSense (e.g. /home/legion/flowsense on WSL)
mkdir -p logs
nohup python connector.py --camera-id 30 --track > logs/camera_30.log 2>&1 &
echo $! > logs/camera_30.pid
tail -f logs/camera_30.log
```

### Production Stop:
```bash
cd "$REPO_DIR"   # REPO_DIR = where you cloned FlowSense (e.g. /home/legion/flowsense on WSL)
kill $(cat logs/camera_30.pid)
rm logs/camera_30.pid
```

---

**Ready to deploy!** Start with Option 1 (foreground) to verify everything works.
