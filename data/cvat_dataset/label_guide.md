# Labeling guide — FlowSense YOLO fine-tune

Goal: a detector that actually counts Kudus traffic (cars, motorcycles, buses,
trucks, bicycles, and pedestrians) on the real CCTV feeds.

## Why this is a manual step
The detector currently ships with stock COCO `yolo11n.pt`. On a real Kudus
frame (data/frame_test.jpg, Jl. Ahmad Yani) it kept **0** of ~60 candidate
boxes at the production threshold (0.35) — the frame visibly holds 1 bus,
3-4 cars, ~2 trucks, and 15-20 motorcycles. A base COCO nano model trained on
US/EU street scenes does not transfer. Fixing it needs ground truth drawn by a
human; auto-labeling (build_dataset.py) would just bake in the base model's
mistakes.

## Steps
1. Grab raw frames:
     .venv/Scripts/python.exe scripts/grab_label_frames.py --limit 8 --max-cameras 6
   (writes data/cvat_dataset/raw/*.jpg — mix junctions, day/night, clear/rain.)

2. Upload frames to CVAT (or Label Studio / Roboflow). Draw a tight box on
   every vehicle/pedestrian. Use exactly these classes:
     car, motorcycle, bus, truck, bicycle, person
   (angkot / becak / 3-wheeler → label as the closest of car/truck/motorcycle;
   note it in remarks; we can add a class later once there's volume.)

3. Export as **YOLO Detection** format. You get, per frame, a `.txt` with lines:
     <class_id> <x_center> <y_center> <width> <height>   # all normalized 0..1
   Drop the .txt files into data/cvat_dataset/labels/train and /val, the images
   into data/cvat_dataset/images/train and /val. Roughly 80/20 split.

4. Confirm data/cvat_dataset/data.yaml `names` order matches the exported
   class_ids (CVAT lets you remap on export).

5. Train + validate:
     .venv/Scripts/python.exe train_yolo.py --epochs 100 --batch 16
   This prints real mAP50 / mAP50-95 / precision / recall on the val split and
   saves runs/train/flowsense_yolo/weights/best.pt.

6. Drop the new weights in: set FLOWSENSE_MODEL (or --model) to the best.pt
   path and re-run scripts/eval_detector.py to confirm lift over yolo11n.pt.

## Targets worth hitting before shipping
- mAP50 >= 0.80 on val, recall on motorcycle >= 0.85 (they're the dominant
  Kudus vehicle and the smallest/fastest to miss).
- Then re-run the eval harness and confirm `total_kept` > 0 on frame_test.jpg.
