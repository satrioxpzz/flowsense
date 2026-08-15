"""Qwen3.5-9B multimodal vision helper for FlowSense's local connector.

Purpose: given a cropped frame from YOLOv11, ask Qwen3.5 (a native
multimodal vision-language model) for reasoning that YOLO's bounding boxes
alone can't provide -- traffic violations, pedestrian classification,
accident detection, and more.

This is designed to be called occasionally on YOLO's flagged crops, NOT on
every frame -- Qwen is far slower than YOLO and isn't meant for the
real-time path.

Requirements:
    pip install requests
    Ollama must be running locally (ollama serve) with the model pulled:
    ollama pull qwen3.5:9b

    For the fine-tuned FlowAI model (after training):
    ollama create flowai -f config/flowai_modelfile
"""
import base64
import json
import re

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
# Use "flowai" after fine-tuning, or "qwen3.5:9b" for the base model.
MODEL_NAME = "qwen3.5:9b"


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


# ── FlowAI Traffic Violation Detectors ──────────────────────────────────
# Each function below analyses a YOLO-cropped image for a specific traffic
# violation or classification task.  They all share the same fail-safe
# pattern: on any error, return a conservative fallback dict so the caller
# never crashes.


def detect_helmet(image_path: str, timeout: int = 30) -> dict:
    """Check whether a motorcycle rider is wearing a helmet."""
    prompt = (
        "Analyze this CCTV crop of a motorcycle rider. "
        "Determine if the rider is wearing a helmet. "
        "Respond with ONLY a JSON object: "
        '{"wearing_helmet": true/false, "confidence": "high|medium|low", '
        '"notes": "brief reason"}'
    )
    try:
        return _extract_json(describe_frame(image_path, prompt, timeout))
    except (requests.RequestException, ValueError, KeyError) as e:
        return {"wearing_helmet": None, "confidence": "low",
                "notes": f"classification failed: {e}"}


def detect_seatbelt(image_path: str, timeout: int = 30) -> dict:
    """Check whether a car driver is wearing a seatbelt."""
    prompt = (
        "Analyze this CCTV crop of a car occupant. "
        "Determine if the driver is wearing a seatbelt. "
        "Respond with ONLY a JSON object: "
        '{"wearing_seatbelt": true/false, "confidence": "high|medium|low", '
        '"notes": "brief reason"}'
    )
    try:
        return _extract_json(describe_frame(image_path, prompt, timeout))
    except (requests.RequestException, ValueError, KeyError) as e:
        return {"wearing_seatbelt": None, "confidence": "low",
                "notes": f"classification failed: {e}"}


def detect_phone_usage(image_path: str, timeout: int = 30) -> dict:
    """Detect whether a driver or rider is using a mobile phone."""
    prompt = (
        "Analyze this CCTV crop of a driver or rider. "
        "Determine if the person is using a mobile phone while driving. "
        "Respond with ONLY a JSON object: "
        '{"using_phone": true/false, "hand_position": "left|right|both|none", '
        '"confidence": "high|medium|low", "notes": "brief reason"}'
    )
    try:
        return _extract_json(describe_frame(image_path, prompt, timeout))
    except (requests.RequestException, ValueError, KeyError) as e:
        return {"using_phone": None, "hand_position": "none",
                "confidence": "low", "notes": f"classification failed: {e}"}


def detect_headset(image_path: str, timeout: int = 30) -> dict:
    """Detect whether a driver or rider is wearing headphones/earbuds."""
    prompt = (
        "Analyze this CCTV crop of a driver or rider. "
        "Determine if the person is wearing headphones or earbuds. "
        "Respond with ONLY a JSON object: "
        '{"wearing_headset": true/false, '
        '"headset_type": "over-ear|in-ear|none|unclear", '
        '"confidence": "high|medium|low", "notes": "brief reason"}'
    )
    try:
        return _extract_json(describe_frame(image_path, prompt, timeout))
    except (requests.RequestException, ValueError, KeyError) as e:
        return {"wearing_headset": None, "headset_type": "unclear",
                "confidence": "low", "notes": f"classification failed: {e}"}


def classify_pedestrian(image_path: str, timeout: int = 30) -> dict:
    """Classify a pedestrian by age group and mobility aid status."""
    prompt = (
        "Analyze this CCTV crop of a pedestrian. Classify the person. "
        "Respond with ONLY a JSON object: "
        '{"category": "adult|child|elderly", "has_mobility_aid": true/false, '
        '"aid_type": "wheelchair|cane|walker|crutches|none", '
        '"estimated_age_group": "child|teen|adult|elderly", '
        '"confidence": "high|medium|low", "notes": "brief reason"}'
    )
    try:
        return _extract_json(describe_frame(image_path, prompt, timeout))
    except (requests.RequestException, ValueError, KeyError) as e:
        return {"category": "adult", "has_mobility_aid": None,
                "aid_type": "unclear", "estimated_age_group": "adult",
                "confidence": "low", "notes": f"classification failed: {e}"}


def detect_illegal_parking(image_path: str, timeout: int = 30) -> dict:
    """Determine if a vehicle appears to be illegally parked."""
    prompt = (
        "Analyze this CCTV crop of a vehicle. "
        "Determine if it appears to be illegally parked. "
        "Respond with ONLY a JSON object: "
        '{"is_parked": true/false, "blocking_traffic": true/false, '
        '"confidence": "high|medium|low", "notes": "brief reason"}'
    )
    try:
        return _extract_json(describe_frame(image_path, prompt, timeout))
    except (requests.RequestException, ValueError, KeyError) as e:
        return {"is_parked": None, "blocking_traffic": None,
                "confidence": "low", "notes": f"classification failed: {e}"}


def detect_accident(image_path: str, timeout: int = 30) -> dict:
    """Analyse a scene crop for traffic accident indicators."""
    prompt = (
        "Analyze this CCTV scene. Determine if this shows a traffic accident. "
        "Respond with ONLY a JSON object: "
        '{"is_accident": true/false, '
        '"severity": "minor|moderate|severe|none", '
        '"vehicle_count": <int>, "has_injuries": "yes|no|unclear", '
        '"confidence": "high|medium|low", "notes": "brief reason"}'
    )
    try:
        return _extract_json(describe_frame(image_path, prompt, timeout))
    except (requests.RequestException, ValueError, KeyError) as e:
        return {"is_accident": None, "severity": "none",
                "vehicle_count": 0, "has_injuries": "unclear",
                "confidence": "low", "notes": f"classification failed: {e}"}