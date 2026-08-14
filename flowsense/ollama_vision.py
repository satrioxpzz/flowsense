"""Qwen3.5-9B vision helper for FlowSense's local connector.

Purpose: given a cropped frame from YOLOv11 (e.g. a detected pedestrian),
ask Qwen for extra reasoning that YOLO's bounding boxes alone can't give you --
specifically, whether the person appears to be using a mobility aid, so the
adaptive crossing-time logic can act on it.

This is designed to be called occasionally on YOLO's flagged crops, NOT on
every frame -- Qwen is far slower than YOLO and isn't meant for the
real-time path.

Requirements:
    pip install requests
    Ollama must be running locally (ollama serve) with the model pulled:
    ollama pull qwen3.5:9b-q4_K_M
"""
import base64
import json
import re

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen3.5:9b-q4_K_M"


def _image_to_b64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _extract_json(text: str) -> dict:
    """Qwen sometimes wraps JSON in ```json fences or adds text around it.
    This pulls out the first {...} block and parses it."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model output: {text!r}")
    return json.loads(match.group(0))


def describe_frame(image_path: str, prompt: str, timeout: int = 30) -> str:
    """General-purpose: send an image + free-text prompt, get back raw text."""
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [_image_to_b64(image_path)],
            }
        ],
        "stream": False,
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def detect_accessibility_needs(image_path: str, timeout: int = 30) -> dict:
    """FlowSense-specific: classify a YOLO-cropped pedestrian frame for
    mobility aid usage, so the crossing-time logic can extend green time
    accordingly.

    Returns a dict like:
        {
            "has_mobility_aid": bool,
            "aid_type": "wheelchair" | "cane" | "walker" | "none" | "unclear",
            "notes": str
        }
    Falls back to a safe "unclear" result on any parsing/connection failure --
    treat that as "assume needs extra time" in your calling code, don't
    silently drop the detection.
    """
    prompt = (
        "You are analyzing a cropped CCTV frame of a pedestrian at a road "
        "crossing. Determine if they appear to be using a mobility aid "
        "(wheelchair, cane, walker, crutches) or otherwise likely to need "
        "more crossing time. Respond with ONLY a JSON object, no other text: "
        '{"has_mobility_aid": true/false, "aid_type": "wheelchair|cane|'
        'walker|crutches|none|unclear", "notes": "brief reason"}'
    )

    try:
        raw = describe_frame(image_path, prompt, timeout=timeout)
        return _extract_json(raw)
    except (requests.RequestException, ValueError, KeyError) as e:
        return {
            "has_mobility_aid": None,
            "aid_type": "unclear",
            "notes": f"classification failed: {e}",
        }