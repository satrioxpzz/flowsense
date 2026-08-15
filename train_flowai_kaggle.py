"""
train_flowai_kaggle.py

Kaggle notebook training script for fine-tuning Qwen3.5-9B -> FlowAI using QLoRA on Kaggle T4 GPU.
Copy these cells to a Kaggle notebook and run sequentially.
"""

# === CELL 1: Install Dependencies ===
"""
!pip install unsloth
!pip install --no-deps unsloth-zoo
!pip install torch torchvision torchaudio
!pip install transformers accelerate bitsandbytes peft trl
"""

# === CELL 2: Upload & Load Training Data ===
"""
# Assuming the JSON dataset (train.json) and images are uploaded as a Kaggle dataset
import json
from datasets import load_dataset
dataset = load_dataset("json", data_files="/kaggle/input/flowai-dataset/train.json", split="train")
print(f"Loaded {len(dataset)} training examples")
"""

# === CELL 3: Load Qwen3.5-9B with Unsloth QLoRA ===
"""
from unsloth import FastVisionModel
import torch

model, tokenizer = FastVisionModel.from_pretrained(
    model_name="unsloth/Qwen3.5-VL-9B-Instruct-bnb-4bit",
    load_in_4bit=True,
    use_gradient_checkpointing="unsloth",
)
"""

# === CELL 4: Configure LoRA Adapters ===
"""
model = FastVisionModel.get_peft_model(
    model,
    finetune_vision_layers=False,
    finetune_language_layers=True,
    finetune_attention_modules=True,
    finetune_mlp_modules=True,
    r=16,
    lora_alpha=16,
    lora_dropout=0.0,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
)
"""

# === CELL 5: Format Dataset ===
"""
# Apply Unsloth's chat template mapping
from unsloth.chat_templates import get_chat_template

tokenizer = get_chat_template(
    tokenizer,
    chat_template="chatml",
)

def format_dataset(examples):
    # Depending on how the images are stored, mapping image paths in dataset to actual Kaggle paths
    # Assuming Kaggle path prepending is needed or already absolute in dataset
    return examples

# mapped_dataset = dataset.map(format_dataset, batched=True)
mapped_dataset = dataset
"""

# === CELL 6: Training ===
"""
from trl import SFTTrainer
from transformers import TrainingArguments

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=mapped_dataset,
    dataset_text_field="conversations",
    max_seq_length=2048,
    dataset_num_proc=2,
    packing=False,
    args=TrainingArguments(
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        warmup_steps=5,
        num_train_epochs=3,
        learning_rate=2e-4,
        fp16=False,
        bf16=True,
        logging_steps=1,
        optim="paged_adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=3407,
        output_dir="outputs",
        report_to="none",
    ),
)

trainer_stats = trainer.train()
"""

# === CELL 7: Save & Download Adapter ===
"""
output_lora_dir = "flowai-lora-9b"
model.save_pretrained(output_lora_dir)
tokenizer.save_pretrained(output_lora_dir)

print(f"Model saved to {output_lora_dir}")

# Zip for download
import shutil
shutil.make_archive(output_lora_dir, 'zip', output_lora_dir)
from IPython.display import FileLink
FileLink(f'{output_lora_dir}.zip')
"""
