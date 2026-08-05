# Task 4: Config and runner.py updates

**Files:**
- Modify: `flowsense/config.py`
- Modify: `flowsense/runner.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: Sinks from `flowsense/sink.py`
- Modifies: `Config` to have DB and S3 settings.

- [ ] **Step 1: Write failing tests for Config**

Add to `tests/test_config.py`:
```python
def test_db_s3_config_defaults(tmp_path):
    from flowsense.config import load_config
    cfg = load_config(env_path=tmp_path / "missing.env")
    assert cfg.db_url == ""
    assert cfg.s3_endpoint == ""
    assert cfg.s3_access_key == ""
    assert cfg.s3_secret_key == ""
    assert cfg.s3_bucket == ""
```

- [ ] **Step 2: Implement Config fields**

In `flowsense/config.py`, add to `Config`:
```python
    db_url: str = ""
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = ""
```
And in `load_config`, read from `FLOWSENSE_DB_URL`, `FLOWSENSE_S3_ENDPOINT`, etc.

- [ ] **Step 3: Update runner.py to use sinks**

In `flowsense/runner.py`:
Replace `out_path` setup and file writing loop with `JsonlSink`.
Add CLI argument `--sink` (default `"jsonl"`, allow `"jsonl,postgres"`).
Add CLI argument `--snapshot` (flag) to save JPEG to `S3SnapshotSink` every interval.
```python
    record_sinks = []
    if "jsonl" in args.sink:
        record_sinks.append(JsonlSink(out_path))
    if "postgres" in args.sink and cfg.db_url:
        record_sinks.append(PostgresSink(cfg.db_url))

    snap_sink = None
    if getattr(args, 'snapshot', False) and cfg.s3_endpoint:
        snap_sink = S3SnapshotSink(cfg.s3_endpoint, cfg.s3_access_key, cfg.s3_secret_key, cfg.s3_bucket)
```
Inside the `if now - last_emit >= cfg.interval:` loop:
```python
                    record = build_record(...)
                    for sink in record_sinks:
                        try:
                            sink.emit(record)
                        except Exception as e:
                            log.error("sink error", exc_info=True)
                    if snap_sink:
                        ok, buf = cv2.imencode('.jpg', frame)
                        if ok:
                            try:
                                snap_sink.save(camera_key, now, buf.tobytes())
                            except Exception as e:
                                log.error("snap error", exc_info=True)
```
Remove `f.write(...)` directly. Also make sure to import the new sink classes: `from flowsense.sink import JsonlSink, PostgresSink, S3SnapshotSink` in `runner.py`.

- [ ] **Step 4: Commit**

```bash
git add flowsense/config.py flowsense/runner.py tests/test_config.py
git commit -m "feat: wire RecordSink and SnapshotSink into runner"
```
