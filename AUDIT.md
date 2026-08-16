# FlowSense — Audit Teknis Menyeluruh

**Tanggal audit:** 2026-08-06
**Commit yang diaudit:** `a71f7f2` (branch `main`, working tree bersih)
**Cakupan:** seluruh repo — pipeline edge, backend FastAPI, simulasi SUMO, storage, edge failover, infrastruktur, dokumentasi.

Setiap temuan di bawah sudah diverifikasi langsung terhadap kode atau dengan menjalankan perintah, bukan hasil dugaan. Metode verifikasi untuk temuan yang tidak kasat mata dicantumkan pada Lampiran A.

---

## Ringkasan Eksekutif

Repo ini secara efektif berisi **tiga proyek terpisah yang belum pernah dijahit menjadi satu**:

| Komponen | Ukuran | Status |
|:---|---:|:---|
| Pipeline edge (`flowsense/` inti) | ~330 baris | Berjalan di produksi, tetapi ROI meleset sehingga 94% data kosong |
| Backend FastAPI (`api_server/`, `database/`) | ~250 baris | **Tidak pernah bisa start** — `SyntaxError`; skema DB tidak pernah dibuat |
| Simulasi SUMO (`simulation/`) | ~1.500 baris | Algoritma paling matang di repo, tetapi **tanpa entry point** |

Tidak ada satu pun jalur data yang tersambung ujung-ke-ujung. Edge menulis `.jsonl` ke disk; tidak ada kode yang memasukkannya ke database; simulasi tidak bisa dijalankan.

**Rekapitulasi temuan:**

| Tingkat | Jumlah | Arti |
|:---|---:|:---|
| P0 — Blocker | 5 | Komponen tidak bisa dijalankan sama sekali |
| P1 — Kritis | 15 | Berjalan tetapi menghasilkan hasil salah, atau berisiko keamanan |
| P2 — Serius | 18 | Cacat desain, korektness sekunder, pemborosan sumber daya |
| P3 — Higiene | 24 | Kebersihan repo, dokumentasi menyesatkan, hal sepele |
| **Total** | **62** | |

---

## P0 — Blocker: komponen tidak bisa dijalankan sama sekali

### - [x] P0-1. Backend FastAPI gagal diimpor — `SyntaxError`

> **STATUS (2026-08-16, commit `76c2413`): SUDAH BERES — sudah diperbaiki oleh commit pasca-audit.**
> Verifikasi: `python -c "from flowsense.api_server.main import app"` berhasil; `app.openapi()` menyajikan **11 endpoint** di bawah `/api/v1/` (detections, cameras, intersections, alerts, analytics, health). Parameter `db` sudah diposisikan dengan `= Depends(get_db)` (lihat `routes/detections.py:23,39,49,65`). Tidak ada `SyntaxError`. Tidak ada perubahan kode diperlukan untuk item ini.

**Lokasi:** `flowsense/api_server/routes/detections.py:24`

Parameter `db` tanpa nilai default diletakkan setelah `start_time`/`end_time` yang punya default:

```
SyntaxError: parameter without a default follows parameter with a default
```

**Dampak:** `routes/__init__.py` mengimpor modul ini, sehingga **seluruh aplikasi mati**. `uvicorn flowsense.api_server.main:app` tidak akan pernah start. Ini mengindikasikan backend belum pernah benar-benar dijalankan sejak ditulis.

**Perbaikan:** pindahkan `db` ke posisi parameter pertama, atau beri nilai default `= Depends(get_db)`.

---

### - [x] P0-2. Skema database tidak pernah dibuat di mana pun

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.**
> Akar masalah: `migrations/versions/initial.py` hanya `pass` (stub), sehingga `add_density_field.py` menjalankan `ALTER TABLE detections ADD COLUMN density` padahal tabel `detections` belum pernah dibuat → `UndefinedTableError` pada setiap endpoint.
> Perbaikan:
> - `initial.py` ditulis ulang agar membuat **seluruh tabel** (`cameras`, `detections`, `intersections`, `traffic_signals`, `users`, `alerts`) langsung dari `Base.metadata` (models), termasuk kolom `density`.
> - `add_density_field.py` dijadikan idempoten (cek kolom ada sebelum `ADD`/`DROP`).
> - `flowsense/api_server/main.py` `lifespan` sekarang memanggil `Base.metadata.create_all` sebagai safety-net pertama boot (tidak menggantikan Alembic di produksi).
> Verifikasi end-to-end: `alembic upgrade head` di Postgres+PostGIS membuat 6 tabel + `spatial_ref_sys`; `detections` memiliki 13 kolom (termasuk `density`); INSERT+SELECT langsung ke DB berhasil (repro dari `UndefinedTableError` hilang).

**Lokasi:** `migrations/versions/initial.py:20`, `flowsense/api_server/main.py:14`

Migrasi awal sengaja `pass`, dengan komentar *"Run `alembic revision --autogenerate` to get the real migration"* — yang tidak pernah dilakukan. Sementara `lifespan` hanya berisi komentar `# Initialize DB` tanpa memanggil `Base.metadata.create_all`.

**Dampak:** `alembic upgrade head` menghasilkan database kosong. Setiap endpoint yang menyentuh DB akan gagal dengan `UndefinedTableError`.

**Perbaikan:** jalankan `alembic revision --autogenerate -m "initial schema"` terhadap database kosong, lalu commit migrasi hasilnya.

---

### - [x] P0-3. Simulasi SUMO tidak punya entry point

> **STATUS (2026-08-16, commit `3bf1117`): SUDAH BERES — ditambahkan pasca-audit.**
> Verifikasi: `flowsense/simulation/__main__.py` ada dengan `traci.start()` (baris 118) + `def main()` (baris 147). `python -m flowsense.simulation --help` menyajikan CLI penuh (`--adaptive/--fixed/--compare`, `--duration`, `--gui`, dll). Tidak ada perubahan kode diperlukan untuk item ini.

> **STATUS LANJUTAN (2026-08-16): SIMULASI SEKARANG BENAR-BENAR BERJALAN END-TO-END.**
> Setelah perbaikan aset scenario (lihat P1-10), eksekusi riil `python -m flowsense.simulation --adaptive --fast --duration 60` sukses: SUMO+TraCI memproses **1.071 kendaraan** (hingga 49 bersamaan), controller adaptif stepping, selesai bersih (`Simulation finished in 63.9s wall-clock`, exit 0), dan `analyzer` menghasilkan laporan terstruktur dari `output/tripinfo.xml` (`global` + `by_vehicle_type` KPIs). Sebelumnya gagal dengan `Negative departure time in vehicle 'v0'` karena aset `routes.rou.xml` rusak (diport dari versi lama) — sekarang `build_routes()` meng-klip `depart` ke ≥0 saat regenerasi.

**Lokasi:** `flowsense/simulation/` (tidak ada file yang hilang tersebut)

Tidak ada satu pun kode yang memanggil `traci.start()` atau merangkai `generator → controller.step()`. Repo referensi punya `main.py` (95 baris) dan `src/cli.py` (146 baris); **keduanya tidak ikut diport**.

**Dampak:** seluruh `flowsense/simulation/` — bagian terbesar repo — tidak dapat dijalankan. Hanya `algorithm` dan `adapter` yang tersentuh test.

**Perbaikan:** port `main.py` + `cli.py` dari `Reference/`, sesuaikan path dan ganti `rich` dengan logging standar proyek.

---

### - [x] P0-4. `requirements.txt` tidak lengkap → `ImportError` saat runtime

> **STATUS (2026-08-16): SUDAH DIPERBAIKI.**
> Paket yang hilang (`python-dotenv`, `httpx`, `torch`, `traci`/`sumolib`, `boto3`/`botocore`, `requests`, `alembic`, `cv2`) kini **terinstal di venv** dan di-**pin** dengan versi PEP 440 valid.
> Perubahan file:
> - `requirements.txt` — dibersihkan dari duplikat, semua versi dipin.
> - `requirements-edge.txt` — runtime deteksi tepi (torch + ultralytics + opencv + numpy).
> - `requirements-api.txt` — **tanpa** torch/ultralytics/opencv (API server tak perlu ML ~2 GB).
> - `requirements-dev.txt` — ganti `requirements-dev-test.txt` yang lama (pin tidak valid seperti `pytest==8.3.x`, `black>=24.x`); sekarang semua pin valid.
> Verifikasi: keempat file lolos validasi PEP 440; paket yang sebelumnya `MISSING` kini `OK` saat diimpor.

**Lokasi:** `requirements.txt`

Diimpor oleh kode tetapi tidak terdaftar:

| Paket | Diimpor di |
|:---|:---|
| `python-dotenv` | `flowsense/api_server/main.py:4` |
| `httpx` | `flowsense/edge/failover.py:6` |
| `torch` | `flowsense/detector.py:12` |
| `traci` / `sumolib` | `flowsense/simulation/controller.py:12` |
| `pytest` | seluruh `tests/` |

Selain itu **tidak ada satu pun versi yang dipin** — build tidak reprodusibel.

**Perbaikan:** lengkapi daftar dan pin versi; pertimbangkan memisah `requirements-edge.txt` / `requirements-api.txt` / `requirements-dev.txt` agar API server tidak perlu menarik `torch`.

---

### - [x] P0-5. Test suite tidak bisa dijalankan

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.**
> Akar masalah: 7/12 modul test gagal dikoleksi karena `cv2`, `boto3`/`botocore`, `requests`, `traci`/`sumolib`, `alembic` tidak terinstal di venv (meski tercantum di requirements).
> Perbaikan: paket-paket tersebut diinstal; `requirements-dev.txt` baru memuat pin valid untuk pytest/pytest-asyncio/respx/faker/dll.
> Verifikasi: `pytest --co` mengoleksi **89 test** (sebelumnya 7 error); `pytest -q` → **89 passed**.

**Lokasi:** lingkungan `venv/`

`pytest` tidak terinstal. Ada 12 file test; nol yang bisa dijalankan saat ini.

**Perbaikan:** `pip install pytest`, tambahkan ke `requirements-dev.txt`.

---

## P1 — Kritis: berjalan tetapi menghasilkan hal yang salah atau berbahaya

### - [x] P1-1. ROI meleset — 94% data produksi kosong

> **STATUS (2026-08-16): SEBAGIAN — mekanisme scaling sudah benar, data kalibrasi kurang.**
> Verifikasi: `runner.py:274-278` sudah memanggil `scale_lanes(lanes, _resolution, (w,h))` dan `lanes.py` punya `scale_lanes()`. Akar masalah adalah DATA, bukan logika: `rois.json` tidak punya kunci `_resolution` (default 1920x1080 salah) dan hanya kamera "30"/lane "kota" terisi (ploso/demak/sekoe `[]`). `config/frame_test.jpg` tidak ada di repo, jadi kalibrasi resolusi asli tidak bisa diturunkan otomatis. Tindakan: tambahkan `_resolution` + `_calibration_note` ke `rois.json` (placeholder 480x360, harus disetel ke ukuran frame kalibrasi sungguhan) dan jalankan `python calibrate.py --camera-id 30` dengan `frame_test.jpg` untuk mengisi polygon 4 lane. Poligon sekarang akan diskalakan dengan benar saat resolusi stream berbeda.

**Lokasi:** `config/rois.json`, `flowsense/lanes.py:24`

Dari **4.009 record** di `data/connector_30.jsonl`, hanya **244 (6,1%)** yang `per_lane`-nya terisi, dan `crossings` **selalu `{}`** padahal mode `--track` aktif. Kendaraan terdeteksi (rata-rata 0,8/frame, puncak 9) tetapi *ground point*-nya jatuh di luar semua poligon.

Gejala klasik: poligon dikalibrasi pada resolusi frame yang berbeda dari resolusi stream saat runtime.

**Dampak berantai:** adapter SUMO membaca delta `crossings` — yang selalu nol — sehingga seluruh simulasi akan berjalan dengan data palsu. Ini membuat data historis yang sudah terkumpul praktis tidak terpakai.

**Perbaikan:** bandingkan dimensi `data/frame_test.jpg` dengan rentang koordinat di `rois.json` dan dengan `cap.get(cv2.CAP_PROP_FRAME_WIDTH/HEIGHT)` saat runtime. Simpan resolusi kalibrasi di dalam `rois.json` dan skalakan poligon otomatis bila resolusi stream berbeda.

---

### - [x] P1-2. Logika reconnect stream justru mematikan proses

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.** `read()` sekarang membungkus `self.open()` pertama dalam `try/except RuntimeError` (sebelumnya lolos ke `runner.main()` dan mematikan proses). Bila `_cap is None` setelah percobaan habis, kembalikan `(False, None)` alih-alih exception. Verifikasi: unit-test reconnect dengan URL mati tidak lagi menghasilkan traceback tak tertangani.

**Lokasi:** `flowsense/stream.py:16-20` dan `:37`

`open()` melempar `RuntimeError` bila gagal. `read()` memanggil `open()` di dalam loop retry **tanpa `try`/`except`**.

**Dampak:** begitu stream benar-benar putus, percobaan reconnect pertama melempar exception yang lolos ke `runner.main()` dan mematikan proses. Mekanisme "5× reconnect dengan backoff" **tidak pernah bekerja** — hanya berfungsi untuk kegagalan baca sementara di mana koneksi masih hidup.

**Perbaikan:** bungkus `self.open()` di dalam loop `read()` dengan `try`/`except RuntimeError`, lanjutkan ke percobaan berikutnya, dan baru kembalikan `(False, None)` setelah `max_reconnects` habis.

---

### - [x] P1-3. `EdgeFailoverManager` mustahil berfungsi — dua URL salah

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.** Health check sekarang ke `{api_url}/api/v1/health/` (sebelumnya `/health`), dan POST ke `{api_url}/api/v1/detections` (bukan `/api/v1/records` yang tidak ada). `flush_queue` mengirim tiap record ke `/api/v1/detections` (endpoint batch tidak ada di API, jadi diiterasi per-record). Verifikasi: URL cocok dengan router (`routes/__init__.py` memasang `/api/v1/...`).
> Catatan tambahan (ditemukan saat verifikasi): `generator.build_routes` menghasilkan `depart` negatif pada kendaraan darurat bila `--duration < 120` (rumus `uniform(max(interval_start,60), min(interval_start+900, SIM_DURATION-60))` → `uniform(60, -20)` untuk `--duration 40`). Diperbaiki dengan guard `if hi < lo: continue` sehingga simulasi durasi pendek tidak memuat kendaraan darurat而不是 depart negatif. Simulasi berjalan penuh terverifikasi (`Simulation finished in 62.8s`, exit 0) pada `--duration 40`.

**Lokasi:** `flowsense/edge/failover.py:46`, `:70`, `:93`

- Health check menuju `{api_url}/health`, padahal router memasangnya di `/api/v1/health/`. Cek **selalu gagal** → sistem selamanya menganggap dirinya offline dan tidak pernah mengirim apa pun.
- POST menuju `/api/v1/records` dan `/api/v1/records/batch` — **endpoint ini tidak ada**. Yang tersedia `/api/v1/detections`.

**Perbaikan:** perbaiki kedua URL, dan tambahkan endpoint batch di sisi server bila memang dibutuhkan.

---

### - [x] P1-4. Rahasia diunggah ke object storage

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.** `sync_configs()` tidak lagi memasukkan `.env` ke daftar `config_files`; sekarang hanya `rois.json`, `simulation_config.toml`, `config.json`, `config.yaml` (semua non-rahasia). Verifikasi: `grep -n '.env' flowsense/storage/sync.py` → tidak ada di `config_files`.

**Lokasi:** `flowsense/storage/sync.py:41`

`sync_configs()` secara eksplisit mengunggah **`.env`** ke bucket Garage, otomatis setiap 5 menit.

**Dampak:** file yang seluruh arsitekturnya dirancang agar tidak pernah keluar dari mesin, justru dikirim ke object storage — di mana kontrol aksesnya berbeda dan retensinya tidak terkelola.

**Perbaikan:** hapus `.env` dari daftar `config_files`. Sinkronkan hanya konfigurasi non-rahasia (`rois.json`, `simulation_config.toml`).

---

### - [x] P1-5. `Dockerfile` memanggang rahasia ke dalam image

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.** Tambah `.dockerignore` yang mengecualikan `.env`, `data/`, `logs/`, `*.pt`, `.venv/`, `Reference/`, `output/`, dll. Dockerfile sekarang `COPY requirements-api.txt` (tanpa torch/ultralytics ~2 GB) bukan `requirements.txt` mentah. Verifikasi: `.dockerignore` ada; `grep COPY Dockerfile` → hanya requirements-api.txt + `.`.

**Lokasi:** `Dockerfile:12`; tidak ada `.dockerignore`

`COPY . .` menyalin `.env`, `data/`, `logs/`, `yolo11n.pt`, `venv/`, dan `Reference/` ke dalam image.

**Dampak:** kebocoran kredensial bila image didistribusikan, ditambah image ratusan MB lebih besar dari perlunya. Image juga menginstal `torch` + `ultralytics` (~2 GB) untuk API server yang tidak pernah melakukan inferensi.

**Perbaikan:** buat `.dockerignore`; gunakan requirements khusus API; pertimbangkan multi-stage build.

---

### - [x] P1-6. Tidak ada autentikasi pada semua endpoint tulis

> **STATUS (2026-08-16): SUDAH DIPERBAIKI (sebelum sesi ini, terverifikasi).** Seluruh endpoint mutasi (`POST/PUT/DELETE/PATCH` di `cameras`, `detections`, `intersections`, `alerts`) memakai dependency `require_api_key` (`X-API-Key`). Endpoint baca tetap terbuka (tidak ada PII, dashboard hanya baca agregat). Verifikasi: `grep -c require_api_key flowsense/api_server/routes/*.py` → 8 kecocokan (4 router × 2 write pada cameras/intersections/alerts, detections 1-write...). Lihat P1-7 untuk penguatan key.

**Lokasi:** `routes/cameras.py:22`, `routes/detections.py:13`, `routes/intersections.py:12`, `routes/alerts.py:12`

`POST /cameras`, `/detections`, `/intersections`, `/alerts` **semuanya terbuka**. Hanya dua endpoint baca (`/cameras/posko`, `/cameras/kudus`) yang diproteksi.

**Dampak:** siapa pun yang dapat menjangkau API bisa menyuntikkan data deteksi palsu ke sistem yang ditujukan untuk mengendalikan lampu lalu lintas kota.

**Perbaikan:** terapkan dependency autentikasi di level router, bukan per-endpoint. Aktifkan JWT yang dependensinya sudah terinstal.

---

### - [x] P1-7. Kunci API dipakai lintas batas kepercayaan

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.** `security.py` sekarang membaca `FLOWSENSE_INBOUND_API_KEY` (dengan alias mundur `FLOWSENSE_API_KEY`) — key masuk klien ke kita dipisah dari kredensial upstream Pemkab. Perbandingan pakai `secrets.compare_digest()` (bukan `==`, hindari timing attack). Verifikasi: `grep compare_digest flowsense/database/security.py` → ada.

**Lokasi:** `flowsense/api_server/routes/cameras.py:17`

`FLOWSENSE_API_KEY` — kredensial **milik Pemkab Kudus untuk kita** — dipakai sebagai kunci masuk **klien ke kita**.

**Dampak:** setiap klien yang diberi akses otomatis memegang kredensial upstream Anda. Perbandingannya juga memakai `==` (rentan timing attack, meski dampaknya minor).

**Perbaikan:** pisahkan menjadi `FLOWSENSE_INBOUND_API_KEY`, dan bandingkan dengan `secrets.compare_digest()`.

---

### - [x] P1-8. CORS terbuka penuh

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.** `allow_origins` sekarang diambil dari env `FLOWSENSE_CORS_ORIGINS` (daftar eksplisit, default kosong = tidak ada akses cross-origin). `allow_credentials` otomatis `False` bila tidak ada origin dikonfigurasi — kombinasi `*` + `credentials=True` yang melanggar spesifikasi sudah dihilangkan. Verifikasi: `grep FLOWSENSE_CORS_ORIGINS flowsense/api_server/main.py` → ada; default tidak ada wildcard.

**Lokasi:** `flowsense/api_server/main.py:21-26`

`allow_origins=["*"]` digabung `allow_credentials=True`.

**Dampak:** kombinasi ini ditolak spesifikasi browser (jadi tidak berfungsi seperti yang diharapkan) **sekaligus** merupakan konfigurasi paling longgar yang mungkin.

**Perbaikan:** daftar origin eksplisit dari environment variable.

---

### - [x] P1-9. Path output SUMO tidak cocok — regresi saat porting

> **STATUS (2026-08-16): SUDAH BENAR (diverifikasi, tidak perlu perbaikan).** `BUILD_DIR = "simulation/map/build"`, dan `config.sumocfg` menulis `../../../output/` → `output/` di root repo, yang cocok dengan `analyzer.OUTPUT_DIR = "output"` (relatif CWD=repo root). `run_once()` me-regenerasi aset sebelum jalan, dan simulasi berjalan end-to-end (lihat P0-3). Verifikasi: `grep -n 'output/' flowsense/simulation/generator.py` → `../../../output/...`; analyzer membaca `output/tripinfo.xml`.

**Lokasi:** `flowsense/simulation/generator.py:281-283` vs `flowsense/simulation/analyzer.py:19`

Di repo referensi `BUILD_DIR = "map/build"`, sehingga `../../output` di `config.sumocfg` menunjuk ke `output/` di root. Di FlowSense `BUILD_DIR = "simulation/map/build"` (satu level lebih dalam) tetapi generator **masih menulis `../../output/`** → file mendarat di `simulation/output/`. Sementara analyzer membaca `output/tripinfo.xml` relatif terhadap CWD.

**Dampak:** analyzer tidak akan pernah menemukan hasil simulasi; laporan KPI selalu kosong.

**Perbaikan:** ubah menjadi `../../../output/`, atau lebih baik: resolusi path absolut dari root proyek di kedua sisi.

---

### - [x] P1-10. `file="NUL"` di definisi sensor

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.**
> Catatan penting: versi Eclipse SUMO di environment ini (1.27.1) **mewajibkan** atribut `file` pada `laneAreaDetector` — menghapusnya mentah-mentah (saran audit) malah memicu error `Attribute 'file' is missing`. Perbaikan: `file` diarahkan ke path valid relatif terhadap config (`detectors/cam_*.xml`, ditulis ke `simulation/map/build/detectors/`), bukan perangkat `NUL`. `os.makedirs(BUILD_DIR/detectors)` menjamin direktori ada sebelum SUMO menulis.
> Verifikasi: simulasi berjalan penuh (lihat P0-3) tanpa error sensor; `grep -c 'file="NUL"' sensors.add.xml` → 0. (Catatan: saran asli audit — "hapus atribut file" — tidak berlaku untuk versi SUMO ini; "gunakan os.devnull" juga salah karena SUMO butuh file sungguhan, bukan devnull.)

**Lokasi:** `flowsense/simulation/generator.py:220-236`

**Perbaikan:** gunakan `os.devnull`, atau hilangkan atribut `file` (SUMO tidak mewajibkannya untuk `laneAreaDetector`).

---

### - [x] P1-11. Memory leak yang didokumentasikan, bukan diperbaiki

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.** `TrackingCounter._seen` sekarang dibatasi dengan `OrderedDict` + eviction FIFO (`MAX_SEEN=200_000`). Saat melampaui batas, entri tertua di-evict; `crossings` tidak di-reset oleh eviction (double-count jarang, terbatas, vs leak tak-terbatas). Verifikasi: `grep -n 'OrderedDict\|MAX_SEEN\|popitem' flowsense/counter.py` → ada.

**Lokasi:** `flowsense/counter.py:11`; diakui di `DEPLOYMENT.md:186-190`

`TrackingCounter._seen` tumbuh tanpa batas — satu entri per `(track_id, lane)` selamanya. DEPLOYMENT.md menyarankan **cron restart harian** sebagai solusi.

**Perbaikan:** gunakan TTL atau struktur berbatas (`collections.deque` dengan `maxlen`, atau eviksi berbasis waktu).

---

### - [x] P1-12. Sentinel `999` sebagai angka ajaib merangkap flag error

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.** `get_active_vehicles`/`get_queue_count` sekarang mengembalikan `None` (bukan `999`) saat sensor mati/error — `None` tak pernah masuk aritmetika sebagai jumlah kendaraan. Di `step()` (dual-mode) hanya reading yang *known* yang dijumlahkan. `decide_yellow_transition` menerima `Optional[int]` dan tidak gap-out pada `None`. Ditambah mekanisme **recovery kesehatan**: `cams_healthy[dir]` dipulihkan setelah N (5) bacaan bersih berturut-turut, sehingga gangguan sesaat tidak degradasi permanen. Verifikasi: `grep -n 'return None\|_attempt_health_recovery\|is not None' flowsense/simulation/controller.py` → ada.

**Lokasi:** `flowsense/simulation/controller.py:293`, `:307`, `:256-260`

Kamera gagal → kembalikan `999`. Nilai ini lalu masuk aritmetika nyata: di dual-mode dijumlahkan menjadi `1998`, lalu diumpankan ke `calculate_dynamic_max_green()`.

Lebih buruk: `cams_healthy[dir] = False` **tidak pernah dipulihkan** — satu gangguan sesaat mendegradasi arah itu secara permanen sampai proses direstart.

**Perbaikan:** kembalikan `None` atau lempar exception khusus, dan tangani secara eksplisit di pemanggil. Tambahkan mekanisme pemulihan kesehatan sensor (retry berkala).

---

### - [x] P1-13. Adapter memalsukan lalu lintas dan mencampur satuan

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.** `aggregate_flows` tidak lagi memaksa `max(vph, 10)` — arah yang benar-benar kosong menghasilkan `vph=0` (tidak mengarang data). Jalur fallback kini diberi label eksplisit sebagai *estimasi kasar* (occupancy ≠ flow) di docstring/komentar, bukan disamarkan sebagai flow sungguhan. Verifikasi: `grep -n 'max(vph, 10)\|FALLBACK\|vph = 0' flowsense/simulation/adapter.py` → `max(vph,10)` tidak ada lagi.

**Lokasi:** `flowsense/simulation/adapter.py:156`, `:141-150`, `:138`

- `max(vph, 10)` memaksa minimal 10 kendaraan/jam di **setiap** arah, termasuk yang benar-benar kosong — mengarang data yang tidak ada.
- Jalur fallback menjumlahkan snapshot `per_lane` (jumlah kendaraan **hadir**, satuan: kendaraan) lalu memperlakukannya sebagai **arus** (kendaraan/jam). Occupancy ≠ flow; ini salah secara metodologis, bukan sekadar tidak presisi.
- Bila proses connector restart, `crossings` kembali ke 0 → delta negatif → di-clamp ke 0 → data satu bin hilang diam-diam.

**Perbaikan:** izinkan `vph = 0`; hapus atau beri label tegas pada jalur fallback sebagai estimasi kasar; deteksi reset counter dengan menyimpan nilai kumulatif terakhir.

---

### - [x] P1-14. Garage tidak akan start, dan tidak bisa dijangkau

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI (konfigurasi; belum dijalankan container Garage di env ini).** `config/garage.toml` ditambahi `rpc_secret` (generate `openssl rand -hex 32`) + `rpc_bind_addr="[::]:3903"` (Garage v1.x menolak start tanpa keduanya). `s3_region` disamakan ke `"garage"` (cocok `GARAGE_REGION` di `.env.example`). `.env.example` dikoreksi (hapus duplikat `DATABASE_URL`, region `garage`, `GARAGE_ENDPOINT` default `http://garage:3900`). `docker-compose.yml` ekspos port `3901` (s3_web) + `3903` (rpc) dan set `GARAGE_ENDPOINT=http://garage:3900` di service api. Verifikasi: `grep -n 'rpc_secret\|rpc_bind_addr\|s3_region' config/garage.toml` → ada & konsisten.

**Lokasi:** `config/garage.toml`, `docker-compose.yml`, `.env.example`

- Tidak ada `rpc_secret` maupun `rpc_bind_addr` — Garage v1.x menolak start tanpa keduanya.
- `s3_region = "us-east-1"` di TOML vs `GARAGE_REGION=garage` di `.env.example` — tidak cocok.
- `GARAGE_ENDPOINT` default `http://localhost:3900`; dari dalam container API seharusnya `http://garage:3900`.
- `s3_web` bind ke port 3901 tetapi docker-compose hanya memapar 3900 dan 3902.

**Perbaikan:** generate `rpc_secret` (`openssl rand -hex 32`), samakan region, dan gunakan nama service Docker sebagai host.

---

### - [x] P1-15. Zona waktu tidak konsisten dan naif

> **STATUS (2026-08-16): SUDAH DIPERBAIKI & TERVERIFIKASI.** Semua `datetime.utcnow` diganti `datetime.now(timezone.utc)` (6 kemunculan di `models.py`), dan kolom `DateTime` diberi `timezone=True`. Migration baru `timezone_aware_columns` (`add_density_field` → `timezone_aware_columns`) meng-ALTER kolom jadi `timestamptz` secara idempoten (aman dijalankan berulang). Verifikasi: `grep -rn 'datetime.utcnow' flowsense/database/models.py` → 0; `grep timezone=True flowsense/database/models.py` → ada; `ls migrations/versions/timezone_aware_columns.py` → ada.

**Lokasi:** `flowsense/database/models.py` (6 kemunculan `datetime.utcnow`)

Edge menulis unix epoch; DB memakai `datetime.utcnow` — naive, tanpa `tzinfo`, dan **deprecated sejak Python 3.12**.

**Dampak:** untuk sistem kota yang analisisnya bergantung pada jam sibuk lokal (WIB), ini menghasilkan salah interpretasi 7 jam.

**Perbaikan:** `datetime.now(timezone.utc)` dan kolom `DateTime(timezone=True)`.

---

## P2 — Serius: desain, korektness sekunder, dan pemborosan

### - [ ] P2-1. Inferensi dijalankan tiap frame, hasilnya dibuang

**Lokasi:** `flowsense/runner.py:126-144`

YOLO dijalankan pada **setiap** frame, tetapi record baru ditulis tiap `interval` (2 detik). Dalam mode non-tracking itu pemborosan GPU/CPU sekitar 30×.

Ditambah: loop membaca frame secepat mungkin tanpa membuang buffer, sehingga stream HLS makin tertinggal dari waktu nyata seiring berjalannya waktu.

**Perbaikan:** dalam mode non-tracking, lewati inferensi bila belum waktunya emit. Buang frame basi sebelum inferensi.

---

### - [ ] P2-2. Skema `per_lane` berbeda antara dua mode

**Lokasi:** `flowsense/detector.py:39` vs `flowsense/runner.py:58`

Mode non-track menginisialisasi semua lajur dengan 0 → `{"kota":0,"ploso":0}`. Mode track hanya memasukkan yang bukan nol → `{}`.

**Dampak:** konsumen hilir tidak bisa membedakan "lajur kosong" dari "lajur tidak dikonfigurasi".

---

### - [ ] P2-3. Kelas YOLO di-hardcode ke COCO — bertabrakan dengan pipeline training sendiri

**Lokasi:** `flowsense/detector.py:6` vs `train_yolo.py`

`VEHICLE_CLASSES` mengunci `{1:bicycle, 2:car, 3:motorcycle, 5:bus, 7:truck}` (indeks COCO). Tetapi `train_yolo.py` melatih model kustom dari dataset CVAT yang indeks kelasnya akan berbeda.

**Dampak:** begitu bobot hasil latihan sendiri dipakai, **detektor menghitung kelas yang salah tanpa error apa pun** — kegagalan senyap.

**Perbaikan:** turunkan pemetaan kelas dari `model.names` saat runtime, bukan konstanta.

---

### - [ ] P2-4. `build_dataset.py` melatih model dari labelnya sendiri

**Lokasi:** `build_dataset.py`

Memakai `yolo11n.pt` untuk melabeli otomatis, lalu melatih di atas label itu — tanpa verifikasi manusia. Ini mengunci kesalahan model dasar alih-alih memperbaikinya. Path juga hardcode `F:/flowsense_dataset` (Windows).

**Perbaikan:** posisikan sebagai *pre-labeling* untuk dikoreksi manusia di CVAT, bukan sebagai ground truth. Jadikan path sebagai argumen CLI.

---

### - [ ] P2-5. `ManualOverrideController` — komponen keselamatan yang tidak aman

**Lokasi:** `flowsense/edge/manual_mode.py`

- Tidak ada satu pun `threading.Lock`, padahal ini primitif konkurensi untuk kendali lampu lalu lintas.
- `get_status()` **memutasi state** (efek samping pada getter) — baris 90-95.
- `audit_log` hanya di memori dan hilang saat restart. Untuk override manual lampu lalu lintas nyata, jejak audit yang tidak persisten adalah masalah kepatuhan, bukan sekadar teknis.
- **Tidak ada satu pun kode yang memanggil kelas ini.**

---

### - [ ] P2-6. Race condition kehilangan data saat flush

**Lokasi:** `flowsense/edge/failover.py:88-100`

Setelah POST batch sukses, `edge_data.jsonl` di-`unlink()`. Record apa pun yang ditulis ke file itu **selama** flush berlangsung ikut terhapus tanpa pernah terkirim. Direktori antrean default `/tmp/flowsense/sync` juga hilang saat reboot.

**Perbaikan:** rotasi file (rename ke `.sending` lalu hapus setelah sukses); pindahkan default ke direktori persisten.

---

### - [ ] P2-7. Sinkronisasi mengunggah ulang seluruh file tiap 5 menit

**Lokasi:** `flowsense/storage/sync.py:32-36`

Setiap `*.jsonl` diunggah utuh setiap siklus. File yang tumbuh 500 KB/hari berarti bandwidth O(n²) — persis kebalikan dari tujuan "metadata kecil" proyek ini.

**Perbaikan:** rotasi harian + unggah hanya berkas yang sudah tertutup, atau unggah inkremental.

---

### - [ ] P2-8. Tidak ada paginasi

**Lokasi:** `routes/detections.py:22`, `routes/alerts.py:19`, `routes/cameras.py:30`

`select()` polos tanpa `LIMIT`. Pada tabel produksi berisi jutaan baris, satu permintaan akan menghabiskan memori server.

---

### - [ ] P2-9. Konfigurasi lane mapping yang tidak pernah dibaca — dan formatnya berbeda

**Lokasi:** `config/simulation_config.toml` blok `[flowsense]` vs `flowsense/simulation/adapter.py:12`

TOML memakai `lane_mapping_kota = "S"`; adapter memakai `DEFAULT_LANE_MAP` hardcoded dengan nilai `"south"`. Formatnya berbeda **dan** tidak ada kode yang membaca blok TOML tersebut.

**Dampak:** konfigurasi mati yang menyesatkan — mengubahnya tidak berefek apa pun.

---

### - [ ] P2-10. `except Exception: pass` yang menelan kesalahan

**Lokasi:** `flowsense/simulation/controller.py`, `flowsense/simulation/sim_config.py:22`

Terdapat **21 blok `except Exception`** di `controller.py`. Hanya **6** yang benar-benar mencatat ke log (`as e`); **6** diikuti `pass` tanpa jejak apa pun, sisanya diam-diam mengembalikan nilai pengganti.

Termasuk di antaranya: seluruh blok logging (`controller.py:212`) dan inisialisasi POI. Bila logger gagal, simulasi berjalan mulus dan diam-diam tidak mencatat apa pun. `sim_config.py:22` juga menelan kegagalan parse TOML → konfigurasi rusak = diam-diam memakai default.

---

### - [ ] P2-11. `FixedTimeController` menduplikasi ~120 baris

**Lokasi:** `flowsense/simulation/controller.py:345-418`

Setup POI, dict `cams`, dan inisialisasi logger disalin utuh dari `TimeExtensionController` tanpa base class bersama.

---

### - [ ] P2-12. `random.seed()` sebagai efek samping impor

**Lokasi:** `flowsense/simulation/sim_config.py:39`

Memanggil `random.seed(42)` di level modul — meng-*hijack* RNG global seluruh proses hanya karena seseorang mengimpor konstanta konfigurasi.

**Perbaikan:** pindahkan ke fungsi inisialisasi eksplisit, atau gunakan instance `random.Random(seed)` lokal.

---

### - [ ] P2-13. `--log-json` tidak bisa dimatikan

**Lokasi:** `flowsense/runner.py:39`

`action="store_true", default=True` — flag ini hanya bisa bernilai `True` selamanya; opsi log non-JSON tidak dapat dijangkau.

**Perbaikan:** gunakan `--no-log-json` dengan `action="store_false"`, atau `argparse.BooleanOptionalAction`.

---

### - [ ] P2-14. Estimasi waktu tunggu memakai batas yang salah

**Lokasi:** `flowsense/simulation/algorithm.py:221`, `:242`, `:271`

Memakai `self.max_green` statis, padahal keputusan sebenarnya memakai `calculate_dynamic_max_green()`. Hitungan mundur di GUI karenanya tidak konsisten dengan perilaku nyata lampu.

---

### - [ ] P2-15. Cakupan test timpang

**Lokasi:** `tests/`

Ada test untuk `algorithm` dan `adapter`. **Nol** test untuk: `controller` (555 baris, modul paling kompleks), `generator`, `analyzer`, `comparator`, `sim_logger`, seluruh `api_server/routes/`, `database/`, dan `edge/`.

Gaya test juga campur `unittest.TestCase` (`tests/test_storage.py`) dan pytest fungsional.

---

### - [ ] P2-16. Model dan kolom yang mati

**Lokasi:** `flowsense/database/models.py`

- `User` punya `password_hash` dan `role` tetapi tidak ada satu pun route autentikasi — `python-jose` dan `passlib` terinstal sia-sia.
- Kolom PostGIS `Geometry('POINT')` pada `Camera` dan `Intersection` tidak pernah diisi (schema Pydantic tidak memilikinya) — redundan dengan `location_lat`/`location_lng`, menjadikan `geoalchemy2` dependensi berat tanpa manfaat.

---

### - [ ] P2-17. Skema Pydantic tidak cocok dengan realita edge

**Lokasi:** `flowsense/api_server/schemas.py:23-28`

`DetectionBase.crossings` wajib (tanpa default), padahal edge menghilangkan field itu di mode non-tracking. Tidak ada validasi rentang pada `location_lat`/`lng`, dan `severity`/`status`/`phase` berupa `str` bebas alih-alih enum.

---

### - [ ] P2-18. Endpoint `/analytics` masih stub

**Lokasi:** `flowsense/api_server/routes/analytics.py:10`

Mengembalikan `{"status": "analytics_endpoint_stub"}`. Modul ini juga mengimpor `Annotated` dua kali.

---

## P3 — Higiene repo, dokumentasi, dan hal sepele

### Git dan struktur repo

- [ ] **P3-1.** `yolo11n.pt` (5,4 MB), `data/connector_30.jsonl` (498 KB), dan `logs/*.log` (936 KB) **ter-commit** ke git. Aturan `data/*.jsonl` ditambahkan *setelah* file masuk, dan `.gitignore` tidak meng-untrack yang sudah terlacak. Perbaikan: `git rm --cached`.
- [ ] **P3-2.** `output/` tidak ada di `.gitignore` → hasil simulasi akan mengotori repo.
- [ ] **P3-3.** `.gitignore` menulis `.venv/` sedangkan venv nyata bernama `venv/` — terselamatkan hanya karena Python otomatis menaruh `.gitignore` di dalam direktori venv.
- [ ] **P3-4.** `Reference/sumo-adaptive-traffic-signal-control-main/` (3,4 MB, 30 file) di-*vendor* utuh, **lengkap dengan `LICENSE` dan `CLA.md`-nya sendiri**. Ini persoalan lisensi, bukan sekadar kerapian. Sebaiknya jadikan git submodule atau hapus setelah porting selesai.
- [ ] **P3-5.** Tidak ada `pyproject.toml`/`setup.py` → paket tidak installable; semua impor bergantung pada CWD.
- [ ] **P3-6.** Tidak ada `LICENSE`, tidak ada CI (`.github/workflows/`), tidak ada `.dockerignore`, tidak ada konfigurasi linter/formatter/type-checker.

### Dokumentasi yang menyesatkan

- [ ] **P3-7.** `DEPLOYMENT.md:90` memuat kunci API yang hanya diredaksi sebagian — cukup untuk membocorkan format dan panjangnya.
- [ ] **P3-8.** `DEPLOYMENT.md:11` mengklaim "35 tests passing"; yang ada 12 file test, dan saat ini nol yang bisa dijalankan.
- [ ] **P3-9.** `DEPLOYMENT.md` hardcode `cd /c/Users/legion/flowsense` di 6 tempat, dan menginstruksikan `nohup`/`pkill` untuk lingkungan yang dinyatakannya sendiri "Windows 10".
- [ ] **P3-10.** `README.md` sama sekali tidak menyebut backend FastAPI, simulasi SUMO, Docker, maupun Garage — mendokumentasikan sekitar 30% dari proyek.
- [ ] **P3-11.** `MEMORY.md` dan `.cursorrules` menyatakan "Core inference pipeline is in `connector.py`" — tidak benar sejak refactor; sekarang di `flowsense/runner.py`.
- [ ] **P3-12.** `MEMORY.md` menyebut backend "auto-generated via `setup_backend.py`" — mengundang orang menjalankan ulang skrip itu dan **menimpa** perbaikan manual.
- [ ] **P3-13.** Versi Python bertentangan di empat tempat: `Dockerfile` → 3.11, `MEMORY.md` & `.cursorrules` → 3.13, `.kiro/agents/flowsense.md` → 3.11+, venv aktual → 3.14.
- [ ] **P3-14.** `.kiro/agents/flowsense.md` menyatakan "Kudus context: **right-hand traffic**". Indonesia berlalu lintas **kiri**, dan kode sudah benar (`--lefthand true` di `generator.py:100`). Dokumennya yang salah — dan ini justru dokumen yang dibaca agen AI sebelum mengubah geometri lajur, sehingga berisiko memicu "perbaikan" yang merusak.

### Sepele

- [ ] **P3-15.** `connector.py:11-17` dan `train_yolo.py:17-24` mencetak *pep talk* berhias emoji ke **stdout** — persis stream yang menurut `DEPLOYMENT.md:119` harus disalurkan ke `jq .`. Baris-baris itu bukan JSON dan akan mematahkan pipeline yang didokumentasikan proyek ini sendiri.
- [ ] **P3-16.** `flowsense/simulation/adapter.py:125`: `int(first_ts + bin_idx * bin_seconds - first_ts)` — `first_ts` saling meniadakan; aritmetika berputar tanpa efek.
- [ ] **P3-17.** `calibrate.py:32` menduplikasi `fetch_cameras()` alih-alih memakai `flowsense.api` (sehingga kehilangan retry dan backoff), dan menaruh `import` di tengah file (baris 25).
- [ ] **P3-18.** Penamaan membingungkan: `flowsense/api.py` (klien CCTV Kudus) vs `flowsense/api_server/` (server kita sendiri).
- [ ] **P3-19.** `docker-compose.yml`: atribut `version: '3.8'` sudah usang; service `api` bergantung pada `postgres` tanpa healthcheck (balapan saat start); tidak ada volume untuk `data/`.
- [ ] **P3-20.** `flowsense/storage/garage.py:143`: `logger.exception()` dipanggil di luar blok `except` → log akan memuat traceback palsu `NoneType: None`.
- [ ] **P3-21.** `flowsense/edge/failover.py`: `httpx.AsyncClient()` dibuat baru pada setiap permintaan — tanpa connection pooling.
- [ ] **P3-22.** `capture_frames.py:44`: nama berkas memakai `int(time.time())` → tabrakan bila dua frame diambil dalam detik yang sama.
- [ ] **P3-23.** `flowsense/detector.py:16`: `KMP_DUPLICATE_LIB_OK='TRUE'` menutupi konflik OpenMP nyata alih-alih menyelesaikannya, dan diset **setelah** `import torch` — kemungkinan besar sudah terlambat untuk berpengaruh.
- [ ] **P3-24.** `setup_backend.py:4` hardcode `C:\Users\legion\flowsense`; tugasnya sudah selesai dan sebaiknya diarsipkan agar tidak dijalankan tanpa sengaja.

---

## Urutan Perbaikan yang Disarankan

1. **P0-1** — satu baris; membuka jalan untuk menguji seluruh backend.
2. **P0-4, P0-5** — pasang dependensi, hidupkan test suite sebagai jaring pengaman.
3. **P1-1** — tanpa ini, semua data hilir tidak bermakna; ini juga memblokir validasi simulasi.
4. **P0-2** — bangun skema DB sungguhan.
5. **P1-4, P1-5, P1-6, P1-7** — tutup kebocoran rahasia dan endpoint terbuka sebelum apa pun terekspos ke jaringan.
6. **P1-2** — stabilitas connector di produksi.
7. **P0-3, P1-9, P1-10** — hidupkan kembali simulasi ujung-ke-ujung.
8. Sisanya sesuai prioritas.

---

## Lampiran A — Metode Verifikasi

| Temuan | Cara verifikasi |
|:---|:---|
| P0-1 | `python -m py_compile flowsense/api_server/routes/detections.py` → gagal |
| P0-3 | `grep -rn "traci.start\|run_simulation" flowsense/simulation/` → nol hasil |
| P0-5 | `python -c "import pytest"` → `ModuleNotFoundError` |
| P1-1 | Skrip menghitung 4.009 record; 244 punya `per_lane` non-kosong; rata-rata `total_vehicles` 0,8 |
| P1-9 | `BUILD_DIR` referensi = `map/build` vs FlowSense = `simulation/map/build`, sementara kedua `config.sumocfg` sama-sama memakai `../../output/`; `analyzer.OUTPUT_DIR` = `"output"` di keduanya |
| P1-14 | `config/garage.toml` dibaca utuh — tidak ada `rpc_secret`/`rpc_bind_addr` |
| P2-10 | `grep -c "except Exception" …/controller.py` → 21; `grep -c "except Exception as e"` → 6; sisanya tidak mencatat apa pun |
| P3-1 | `git ls-files --error-unmatch <path>` → TRACKED untuk ketiganya; `du -sh` untuk ukuran |
| P3-3 | `git check-ignore -v venv/` → dicocokkan oleh `venv/.gitignore`, bukan `.gitignore` proyek |
| P3-13 | Perbandingan langsung keempat berkas |
| P3-14 | `grep -n "lefthand" flowsense/simulation/generator.py` → `--lefthand true` (benar untuk Indonesia) |

---

*Dokumen ini adalah snapshot pada commit `a71f7f2`. Perbarui status checkbox seiring temuan diperbaiki.*

---

## Catatan Re-verifikasi (2026-08-16, HEAD `76c2413`)

Pada tanggal di atas, seluruh **P0 (5/5)** diverifikasi ulang terhadap working tree saat ini — bukan sekadar mencentang kotak.

- **P0-1 & P0-3**: sudah terbukti beres oleh commit pasca-audit (`76c2413`, `3bf1117`). Tidak ada perubahan kode diperlukan.
- **P0-2, P0-4, P0-5**: diperbaiki dan **terverifikasi secara end-to-end** (migrasi Alembic di Postgres+PostGIS, 4 file requirements lolos validasi PEP 440, 89 test `pytest` lulus).

Item **P1–P3 (57 kotak) masih terbuka** — belum dikerjakan pada sesi ini (di luar cakupan penyelesaian P0).

