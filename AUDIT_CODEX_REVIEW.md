# FlowSense Audit Changeset Review

Scope: `git diff 76c2413..HEAD` (6 commits), with emphasis on correctness, security, hygiene, and SUMO/detector wiring.

## Verdict / Kesimpulan

**Not ready to approve / Belum siap disetujui.** The `--from-connector` path is structurally connected, but the flow conversion can produce zero or materially incorrect SUMO demand. There are also production-dangerous credential defaults and a committed Garage RPC secret.

Test note / Catatan pengujian: the local environment could not collect tests because `pytest` is not installed. `git diff --check` also reports an extra blank line at EOF in `AUDIT.md:688`.

## Findings / Temuan

### P0 — Inbound API authentication fails open / Autentikasi API inbound gagal tertutup

**Evidence / Bukti:** `flowsense/database/security.py:27-38` falls back to the known literal `secret-api-key-dev`; `.env.example` does not define `FLOWSENSE_INBOUND_API_KEY`, and Compose does not set it.

**Impact / Dampak:** A deployment with missing configuration accepts writes using a public, guessable key. The fallback also conflates the inbound-write key with the upstream `FLOWSENSE_API_KEY`.

**Fix / Perbaikan:** Remove the production fallback and fail startup or reject writes unless a dedicated `FLOWSENSE_INBOUND_API_KEY` is configured. Keep any dev key behind an explicit development-only flag; rotate any exposed key.

### P0 — Committed Garage secret and exposed default credentials / Secret Garage ter-commit dan kredensial default terekspos

**Evidence / Bukti:** `config/garage.toml:8` commits `rpc_secret`; `docker-compose.yml:7-9,24-28,51` uses `flowsense/flowsense`, publishes Postgres and Garage admin/RPC ports, and embeds the database URL.

**Impact / Dampak:** The RPC secret must be treated as compromised. If Compose is reachable beyond an isolated developer machine, database and Garage management surfaces are exposed with trivial credentials.

**Fix / Perbaikan:** Remove the secret from Git, rotate it, inject it through a secret store or protected environment, use unique database credentials, and bind internal/admin ports to localhost or keep them off the host in production.

### P1 — Empty `crossings` records force real demand to zero / Record `crossings` kosong membuat demand nol

**Evidence / Bukti:** `flowsense/simulation/adapter.py:148-162` switches to cumulative-counter mode when any record merely contains the `crossings` key. Historical connector records such as `76c2413:data/connector_30.jsonl` contain `"crossings": {}`; every lookup then returns zero.

**Impact / Dampak:** `--from-connector` can silently generate zero vehicles even when `total_vehicles` is nonzero. This is a direct SUMO behavior regression.

**Fix / Perbaikan:** Select counter mode only when the record has usable numeric counter keys. Define and test the empty/missing-counter behavior explicitly; add a regression fixture for `{}` crossings.

### P1 — Aggregation does not reliably represent flow / Agregasi tidak merepresentasikan arus secara andal

**Evidence / Bukti:** `adapter.py:154-157` computes `last_cross - first_cross` inside each bin, so a bin with one sample always yields zero. Counter baselines are not carried across bins. Without counters, `adapter.py:164-173` averages `per_lane` snapshots and labels the result vehicles/hour, although occupancy is not flow.

**Impact / Dampak:** Sparse detections are undercounted, counter resets can be hidden by `max(0, delta)`, and occupancy snapshots can create materially wrong SUMO demand.

**Fix / Perbaikan:** Specify the connector contract (instantaneous detections vs cumulative counters), use a previous-sample baseline across bins, handle resets explicitly, and do not convert occupancy to vph without a documented calibrated model.

### P1 — Configured real-data source is silently ignored / Sumber data real terabaikan

**Evidence / Bukti:** `config/simulation_config.toml:39` defines `default_data_source`, but `flowsense/simulation/__main__.py:195-202` loads real data only when `--from-connector` is explicitly supplied. Otherwise `run_once` follows the synthetic-volume path.

**Impact / Dampak:** A configured JSONL source does not drive SUMO by default, so an operator can believe the simulation is detector-backed while it is using synthetic demand.

**Fix / Perbaikan:** Resolve the configured source when no explicit CLI source is given, and log the selected source and demand mode.

### P1 — Mixed input schemas can drop demand / Skema campuran dapat menghilangkan demand

**Evidence / Bukti:** `flowsense/simulation/adapter.py:148,158-177` selects `has_crossings` globally. If any record has `crossings`, records without it are treated as zero rather than falling back to `per_lane`.

**Fix / Perbaikan:** Select the representation per record or reject mixed JSONL explicitly.

### P1 — CI omits the test dependency set / CI tidak memasang dependensi test

**Evidence / Bukti:** `.github/workflows/ci.yml:18-26` installs `requirements.txt` and the editable package, then runs pytest. `requirements.txt` and `pyproject.toml` do not install pytest; `requirements-dev.txt` does.

**Impact / Dampak:** A clean CI runner fails before collecting tests (`No module named pytest`). The dev requirements also depend on the separately configured PyTorch index through `requirements-edge.txt`, so a bare install is not self-contained.

**Fix / Perbaikan:** Install `requirements-dev.txt` in CI, or define a proper project test extra, and make the required extra index part of the documented/automated setup.

### P2 — Real-data run reports synthetic congestion metadata / Laporan real-data memakai metadata synthetic

**Evidence / Bukti:** `flowsense/simulation/__main__.py:104-106` correctly applies `set_real_traffic_volumes(real_flows)`, but `run_once()` later calls `print_simulation_report(..., congested=congested)` regardless of `real_flows`.

**Impact / Dampak:** A `--from-connector` report can claim the synthetic `--congested` directions rather than describing the actual demand source, misleading operators and tests.

**Fix / Perbaikan:** Pass an explicit source label and real-flow summary to the analyzer; avoid reporting synthetic congestion flags for real-data runs.

### P2 — Stale/dead configuration and weak input validation / Konfigurasi usang dan validasi input lemah

**Evidence / Bukti:** `config/simulation_config.toml:39` points `default_data_source` at deleted `data/connector_30.jsonl`, but no production code reads it. `adapter.py:135` assigns unused `last_ts`; `--bin-seconds` accepts zero/negative values and can divide by zero or produce invalid bins. The changeset also adds `rotate_detections()` at `flowsense/storage/sync.py:59-76`, but `sync_now()` (`sync.py:97-100`) never calls it and no repository references it.

**Impact / Dampak:** Configuration suggests a supported default that cannot work, while invalid CLI input fails late and unclearly.

**Fix / Perbaikan:** Remove or implement `default_data_source`, remove `last_ts`, wire or remove `rotate_detections()`, and validate `bin_seconds > 0` before aggregation.

## SUMO ↔ detector wiring / Wiring SUMO ↔ detector

The object flow is correct at a structural level / Alur objek benar secara struktural:

`__main__.py --from-connector` → `adapter.load_records()` → `aggregate_flows()` → `run_once(real_flows=...)` → `set_real_traffic_volumes()` → `generator.build_routes()` → SUMO route generation.

`sim_config.TRAFFIC_VOLUME` is mutated in place and `generator.py` consumes that shared dictionary. SUMO subprocess calls use an argument list with `shell=False` behavior, so no shell injection was found in this path.

However, the wiring is **not behaviorally correct yet / belum benar secara perilaku**: the adapter’s empty-counter branch, global schema switch, per-bin baseline, and occupancy-as-flow conversion can feed zero or incorrect vph into SUMO; the configured default source is bypassed. Add tests for empty/mixed crossings, one-record bins, counter resets, default-source selection, and a known multi-bin connector trace before relying on this integration.

## Security/injection summary / Ringkasan keamanan/injeksi

No new shell-evaluation or SQL-string interpolation was found in the reviewed SUMO path. The material security blockers are credential handling, fail-open inbound authentication, and production-unsafe Compose exposure—not command injection.

## Residual hygiene / Sisa hygiene

No actionable `TODO`/`FIXME` marker was found in the changed implementation. Remaining `pass` statements appear to be exception guards or abstract/scaffolding code. The stale config, unused local, uncalled `rotate_detections()` path, and `AUDIT.md` EOF whitespace should still be cleaned up.

## Resolved (2026-08-17) / Sudah diperbaiki

The P0 credential/secret findings above have been remediated and verified
(ad-hoc check: 10/10 PASS; `pytest -q` 110 passed):

- **Inbound auth fail-open** (`security.py`): removed the `secret-api-key-dev`
  fallback AND the `FLOWSENSE_API_KEY` upstream alias. `_expected_api_key()` now
  returns `""` when `FLOWSENSE_INBOUND_API_KEY` is unset, so `require_api_key`
  fails **closed** (HTTP 403) instead of accepting writes with a known default.
- **`.env.example`**: now documents `FLOWSENSE_INBOUND_API_KEY` (required) and
  `POSTGRES_PASSWORD` (no weak default).
- **`docker-compose.yml`**: postgres no longer publishes `5432` and garage no
  longer publishes `3900-3903` to the host (internal network only). Postgres
  creds are parameterized via `${POSTGRES_USER}`/`${POSTGRES_PASSWORD}`.
- **`config/garage.toml`**: committed `rpc_secret` hex replaced with a
  non-functional placeholder; real value lives in `GARAGE_RPC_SECRET` (`.env`).

Deploy note: `.env` must now set `FLOWSENSE_INBOUND_API_KEY` and
`POSTGRES_PASSWORD` (generate strong values) or the stack will refuse writes /
fail to start postgres.

### P1 adapter (2026-08-17) — REMEDIATED

`flowsense/simulation/adapter.py:aggregate_flows` rewritten (verified ad-hoc
7/7; live SUMO sim now injects ~2240 vehicles from `connector_30.jsonl` where
it previously injected ~0/18):

- **Crossings reset bug**: `crossings` is a cumulative per-lane counter that
  resets intermittently. The old code used `last - first` over a bin, which
  collapsed to ~0 vph under resets. Now counts actual crossings as the sum of
  positive per-frame deltas, treating a negative step (reset) as the counter
  wrapping to 0 (increment = post-reset value).
- **Silent lanes stay 0**: `ploso`/`demak`/`sekoe` are never instrumented in
  the real capture, so they correctly yield 0 vph (no fabricated traffic).
- **Occupancy ≠ flow**: the no-`crossings` fallback now uses the authoritative
  per-frame `total_vehicles` (a real count) split by `per_lane` occupancy
  *share* — occupancy is a directional-split proxy only, never scaled to vph.
- Removed unused `last_ts` local.
- Tests added: `test_aggregate_flows_crossing_reset_yields_traffic`,
  `test_aggregate_flows_silent_lanes_zero_on_real_data`,
  `test_aggregate_flows_fallback_uses_total_vehicles_not_occupancy`.

Remaining (still open): P1-CI (install `requirements-dev.txt`), P2 items
(analyzer synthetic congestion on real runs; stale `default_data_source`;
unused `last_ts` in caller; unvalidated `--bin-seconds`).

