"""
build_flowai_training.py

Convert annotation CSV to ShareGPT JSON for Qwen3.5-VL fine-tuning.
"""

import argparse
import csv
import json
import os
from pathlib import Path

SYSTEM_PROMPT = "You are FlowAI, a traffic surveillance AI for Kudus Smart City, Indonesia. You analyze cropped CCTV frames to detect traffic violations, classify road users, and identify anomalies. Always respond with ONLY a valid JSON object."

TASK_PROMPTS = {
    "T1": "Analyze this motorcycle rider. Check if they are wearing a helmet.",
    "T2": "Analyze this car driver/passenger. Check if they are wearing a seatbelt.",
    "T3": "Analyze this person. Check if they are using a mobile phone.",
    "T4": "Analyze this person. Check if they are wearing a headset.",
    "T5": "Analyze this pedestrian. Classify their category and estimate age group.",
    "T6": "Analyze this vehicle. Check if it is illegally parked.",
    "T7": "Analyze this scene. Check for any accident.",
    "T8": "Analyze this scene for any general violations."
}

def generate_template(output_path):
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['image_path', 'task_id', 'json_label'])
        writer.writerow(['F:/flowai_dataset/crops/motorcycle/img1_crop_0.jpg', 'T1', '{"wearing_helmet": true, "confidence": "high", "notes": ""}'])
        writer.writerow(['F:/flowai_dataset/crops/car/img2_crop_1.jpg', 'T2', '{"wearing_seatbelt": false, "confidence": "high", "notes": "driver visible without seatbelt"}'])
        writer.writerow(['F:/flowai_dataset/crops/pedestrian/img3_crop_2.jpg', 'T5', '{"category": "adult", "has_mobility_aid": false, "estimated_age_group": "25-35", "notes": ""}'])
    print(f"Template generated at {output_path}")

def parse_args():
    parser = argparse.ArgumentParser(description="Convert annotation CSV to ShareGPT JSON")
    parser.add_argument("--csv", type=str, default="F:/flowai_dataset/annotations.csv", help="Input CSV path")
    parser.add_argument("--output", type=str, default="F:/flowai_dataset/train.json", help="Output ShareGPT JSON path")
    parser.add_argument("--template", action="store_true", help="Generate a blank CSV template")
    return parser.parse_args()

def main():
    args = parse_args()
    
    if args.template:
        generate_template(args.csv)
        return
        
    if not os.path.exists(args.csv):
        print(f"Error: CSV file {args.csv} not found.")
        return
        
    sharegpt_data = []
    
    with open(args.csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            image_path = row['image_path']
            task_id = row['task_id']
            json_label = row['json_label']
            
            if task_id not in TASK_PROMPTS:
                print(f"Warning: Unknown task_id {task_id} for image {image_path}. Skipping.")
                continue
                
            user_prompt = TASK_PROMPTS[task_id]
            
            try:
                # Validate JSON format
                parsed_json = json.loads(json_label)
                formatted_response = json.dumps(parsed_json, indent=None)
            except json.JSONDecodeError:
                print(f"Warning: Invalid JSON for image {image_path}. Skipping.")
                continue
                
            entry = {
                "system": SYSTEM_PROMPT,
                "conversations": [
                    {
                        "from": "user",
                        "value": f"<image>\n{user_prompt}"
                    },
                    {
                        "from": "assistant",
                        "value": formatted_response
                    }
                ],
                "images": [image_path]
            }
            
            sharegpt_data.append(entry)
            
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(sharegpt_data, f, indent=2)
        
    print(f"Successfully converted {len(sharegpt_data)} annotations to {args.output}")

if __name__ == "__main__":
    main()
