#!/usr/bin/env python3
""" FLOWSENSE PROJECT VALIDATION SCRIPT """

import json
import os
import sys
from pathlib import Path

print('=' * 70)
print('FLOWSENSE PROJECT VALIDATION REPORT')
print('=' * 70)

BASE_DIR = Path(__file__).parent

# 1. ENVIRONMENT CHECK
print('\n1. ENVIRONMENT CHECK:')
env_file = BASE_DIR / '.env'
env_example = BASE_DIR / '.env.example'

if env_file.exists():
    print('   [+] .env exists (gitignored)')
    content = env_file.read_text()
    required_keys = [
        'FLOWSENSE_API_KEY',
        'FLOWSENSE_API_URL',
        'FLOWSENSE_API_TIMEOUT',
        'FLOWSENSE_MIN_CONF',
        'FLOWSENSE_INTERVAL',
    ]
    missing = []
    for key in required_keys:
        if key not in content or f'{key}=' in content and not content.split(f'{key}=')[1].strip().split('\n')[0]:
            missing.append(key)
    if missing:
        print(f'   [!] Missing/incomplete keys: {", ".join(missing)}')
    else:
        print('   [+] All required environment keys present')
else:
    print('   [-] .env file missing')

# 2. CONFIGURATION LOADING
print('\n2. CONFIGURATION LOADING:')
try:
    from flowsense.config import load_config
    cfg = load_config()
    print('   [+] Configuration loaded successfully')
    print(f'      - API URL: {cfg.api_url[:50]}...')
    print(f'      - Model: {cfg.model_path}')
    print(f'      - Interval: {cfg.interval}s')
    print(f'      - Min confidence: {cfg.min_conf}')
except Exception as e:
    print(f'   [-] Configuration loading failed: {e}')

# 3. API CONNECTIVITY
print('\n3. API CONNECTIVITY:')
try:
    import requests
    r = requests.get(cfg.api_url, headers={'X-SDC': cfg.api_key}, timeout=10)
    if r.status_code == 200:
        data = r.json()
        cameras = data.get('camera', [])
        print(f'   [+] API reachable (HTTP {r.status_code})')
        print(f'      - Total cameras: {len(cameras)}')
        print(f'      - Sample: {cameras[0]["id"]} - {cameras[0].get("nama", "N/A")[:30]}')
    else:
        print(f'   [!] API returned {r.status_code}')
except Exception as e:
    print(f'   [-] API connectivity failed: {e}')

# 4. ROI FILES
print('\n4. ROI FILES:')
rois_file = BASE_DIR / 'config' / 'rois.json'
if rois_file.exists():
    print('   [+] rois.json exists')
    try:
        with open(rois_file) as f:
            rois = json.load(f)
        total_lanes = sum(len(v) for v in rois.values())
        calibrated_lanes = sum(sum(1 for pts in lanes.values() if pts) for lanes in rois.values())
        print(f'      - Cameras with ROIs: {len(rois)}')
        print(f'      - Total lane definitions: {total_lanes}')
        print(f'      - Calibrated lanes: {calibrated_lanes}')
        
        uncalibrated = []
        for cam_id, lanes in rois.items():
            for lane_name, points in lanes.items():
                if not points:
                    uncalibrated.append(f'{cam_id}:{lane_name}')
        if uncalibrated:
            print(f'   [!] Uncalibrated lanes: {len(uncalibrated)}')
            for u in uncalibrated[:5]:
                print(f'      - {u}')
            if len(uncalibrated) > 5:
                print(f'      ... and {len(uncalibrated)-5} more')
    except Exception as e:
        print(f'   [-] Failed to parse rois.json: {e}')
else:
    print('   [-] rois.json missing')

# 5. STREAMING URL VERIFICATION
print('\n5. STREAMING URL VERIFICATION (SAMPLE):')
test_urls = [
    ('Dieng (HTTPS)', 'https://cctv.perhubungan.jateng.online/Dieng/index.m3u8'),
    ('Bumiayu MJPEG', 'https://scctv.karanganyarkab.go.id/zm/cgi-bin/nph-zms?scale=100&monitor=48'),
]

for name, url in test_urls:
    try:
        r = requests.head(url, timeout=10, allow_redirects=True)
        status = '[+]' if r.status_code < 400 else '[!]'
        print(f'   {status} {name}: HTTP {r.status_code}')
    except Exception as e:
        print(f'   [-] {name}: {type(e).__name__}')

# 6. DATA FILES
print('\n6. DATA FILES:')
data_dir = BASE_DIR / 'data'
if data_dir.exists():
    jsonl_files = list(data_dir.glob('*.jsonl'))
    json_files = list(data_dir.glob('*.json'))
    print('   [+] data/ directory exists')
    print(f'      - JSONL files: {len(jsonl_files)}')
    print(f'      - JSON files: {len(json_files)}')
else:
    print('   [-] data/ directory missing')

# 7. REQUIRED PYTHON PACKAGES
print('\n7. PYTHON PACKAGES:')
required_packages = ['ultralytics', 'cv2', 'numpy', 'requests', 'fastapi', 'sqlalchemy']
for pkg in required_packages:
    try:
        __import__(pkg.replace('cv2', 'cv2'))
        print(f'   [+] {pkg}')
    except ImportError:
        print(f'   [-] {pkg} (not installed)')

# 8. CAMERA ID ALIGNMENT
print('\n8. CAMERA ID ALIGNMENT:')
try:
    with open(BASE_DIR / 'data' / 'kudus_cctv.json') as f:
        kudus_data = json.load(f)
    with open(BASE_DIR / 'config' / 'rois.json') as f:
        roi_ids = set(json.load(f).keys())
    
    kudus_ids = set(str(cam['id']) for cam in kudus_data)
    mismatch = roi_ids - kudus_ids
    if mismatch:
        print(f'   [!] ROI IDs not in Kudus API: {mismatch}')
    else:
        print('   [+] ROI camera IDs aligned with API')
    print(f'      - API cameras: {len(kudus_ids)}')
    print(f'      - ROI cameras: {len(roi_ids)}')
except Exception as e:
    print(f'   [!] Camera alignment check failed: {e}')

print('\n' + '=' * 70)
print('VALIDATION COMPLETE')
print('=' * 70)