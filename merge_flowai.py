"""
merge_flowai.py

Merge LoRA adapter back into base model for GGUF conversion.
Note: Requires ~32 GB RAM for 9B parameter merge.
"""

import argparse
import torch
from transformers import AutoProcessor
from peft import AutoPeftModelForCausalLM

def parse_args():
    parser = argparse.ArgumentParser(description="Merge FlowAI LoRA with base model")
    parser.add_argument("--base-model", type=str, default="Qwen/Qwen3.5-VL-9B-Instruct", help="Path to base model or HF hub name")
    parser.add_argument("--lora-path", type=str, default="./flowai-lora-9b", help="Path to LoRA adapter")
    parser.add_argument("--output", type=str, default="./flowai-9b-merged", help="Output directory for merged model")
    return parser.parse_args()

def main():
    args = parse_args()
    
    print("WARNING: Merging a 9B model requires ~32 GB of system RAM.")
    print(f"Step 1: Loading base model and LoRA from {args.lora_path} on CPU in FP16...")
    
    try:
        model = AutoPeftModelForCausalLM.from_pretrained(
            args.lora_path,
            device_map="cpu",
            torch_dtype=torch.float16,
        )
    except Exception as e:
        print(f"Error loading model: {e}")
        return
        
    print("Step 2: Merging LoRA weights with base model...")
    merged_model = model.merge_and_unload()
    
    print(f"Step 3: Saving merged model to {args.output}...")
    merged_model.save_pretrained(
        args.output,
        safe_serialization=True,
    )
    
    print("Step 4: Saving processor...")
    processor = AutoProcessor.from_pretrained(args.lora_path)
    processor.save_pretrained(args.output)
    
    print("Merge complete! Model is ready for GGUF conversion.")

if __name__ == "__main__":
    main()
