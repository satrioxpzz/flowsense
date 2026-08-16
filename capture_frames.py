import argparse
import cv2
import os
import time
from flowsense.cctv_client import fetch_cameras
from flowsense.config import load_config
from flowsense.stream import ReconnectingStream

def main():
    parser = argparse.ArgumentParser(description="Capture frames from streams for CVAT AI dataset.")
    parser.add_argument("--out-dir", default="data/cvat_dataset", help="Output directory for frames")
    parser.add_argument("--interval", type=int, default=5, help="Seconds between frames")
    parser.add_argument("--limit", type=int, default=10, help="Max frames per camera")
    args = parser.parse_args()

    cfg = load_config()
    os.makedirs(args.out_dir, exist_ok=True)
    
    cameras = fetch_cameras(cfg)
    if not cameras:
        print("No cameras found. Check API key in .env.")
        return

    for cam in cameras:
        cam_name = cam.get("nama", "unknown").replace(" ", "_")
        cam_url = cam.get("url")
        if not cam_url:
            continue
            
        print(f"Connecting to {cam_name}...")
        stream = ReconnectingStream(cam_url)
        try:
            stream.open()
        except RuntimeError:
            print(f"Failed to open {cam_name}. Skipping.")
            continue
            
        count = 0
        while count < args.limit:
            ok, frame = stream.read()
            if not ok:
                break
                
            # P3-22: use millisecond timestamp + per-camera counter so two
            # frames grabbed in the same second (or across cameras) never
            # overwrite each other.
            ts = int(time.time() * 1000)
            out_path = os.path.join(args.out_dir, f"{cam_name}_{ts}_{count}.jpg")
            cv2.imwrite(out_path, frame)
            count += 1
            print(f"Captured {count}/{args.limit} for {cam_name}")
            
            if count < args.limit:
                time.sleep(args.interval)
                
        stream.release()

if __name__ == "__main__":
    main()
