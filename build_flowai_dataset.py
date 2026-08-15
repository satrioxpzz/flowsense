"""
build_flowai_dataset.py

Auto-crop YOLO detections from CCTV frames for FlowAI training data.
"""

import argparse
import os
import cv2
import torch
from pathlib import Path
from ultralytics import YOLO

# Target COCO classes
TARGET_CLASSES = {
    0: 'pedestrian',
    1: 'bicycle',
    2: 'car',
    3: 'motorcycle',
    5: 'bus',
    7: 'truck'
}

def parse_args():
    parser = argparse.ArgumentParser(description="Crop YOLO detections for FlowAI dataset")
    parser.add_argument("--frames", type=str, default="F:/flowsense_dataset/frames", help="Input frames directory")
    parser.add_argument("--output", type=str, default="F:/flowai_dataset/crops", help="Output crops directory")
    parser.add_argument("--conf", type=float, default=0.40, help="YOLO confidence threshold")
    parser.add_argument("--weights", type=str, default="yolo11n.pt", help="YOLO model weights")
    return parser.parse_args()

def main():
    args = parse_args()
    
    print(f"Checking CUDA availability... CUDA available: {torch.cuda.is_available()}")
    
    frames_dir = Path(args.frames)
    output_dir = Path(args.output)
    
    if not frames_dir.exists():
        print(f"Error: Frames directory {frames_dir} does not exist.")
        return
        
    for class_name in TARGET_CLASSES.values():
        (output_dir / class_name).mkdir(parents=True, exist_ok=True)
        
    print(f"Loading YOLO model from {args.weights}...")
    model = YOLO(args.weights)
    
    image_paths = list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png"))
    total_images = len(image_paths)
    print(f"Found {total_images} images to process.")
    
    class_counts = {name: 0 for name in TARGET_CLASSES.values()}
    
    for idx, img_path in enumerate(image_paths, 1):
        img = cv2.imread(str(img_path))
        if img is None:
            continue
            
        img_h, img_w = img.shape[:2]
        
        results = model(img, conf=args.conf, verbose=False)[0]
        
        for box in results.boxes:
            cls_id = int(box.cls[0].item())
            if cls_id not in TARGET_CLASSES:
                continue
                
            class_name = TARGET_CLASSES[cls_id]
            
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            
            # 15px padding
            pad = 15
            x1 = max(0, int(x1) - pad)
            y1 = max(0, int(y1) - pad)
            x2 = min(img_w, int(x2) + pad)
            y2 = min(img_h, int(y2) + pad)
            
            crop_w = x2 - x1
            crop_h = y2 - y1
            
            if crop_w < 32 or crop_h < 32:
                continue
                
            crop = img[y1:y2, x1:x2]
            
            crop_name = f"{img_path.stem}_crop_{class_counts[class_name]}.jpg"
            crop_path = output_dir / class_name / crop_name
            
            cv2.imwrite(str(crop_path), crop)
            class_counts[class_name] += 1
            
        if idx % 100 == 0:
            print(f"Processed {idx}/{total_images} frames...")
            
    print("\nProcessing complete. Final per-class crop counts:")
    for class_name, count in class_counts.items():
        print(f"  {class_name}: {count}")

if __name__ == "__main__":
    main()
