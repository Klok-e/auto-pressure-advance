"""Render model-selected pointers and clean, enlarged inspection crops."""

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw


def inspection_call(envelope: dict) -> dict | None:
    output = envelope.get("raw", {}).get("output", [])
    if not isinstance(output, list) or any(not isinstance(item, dict) for item in output):
        raise ValueError("model output must contain response items")
    calls = [item for item in output if item.get("type") == "function_call"]
    if not calls:
        return None
    if len(calls) != 1 or calls[0].get("name") != "inspect_region":
        raise ValueError("expected exactly one inspect_region call")
    call = calls[0]
    if not isinstance(call.get("call_id"), str) or not call["call_id"] or not isinstance(envelope.get("id"), str) or not envelope["id"]:
        raise ValueError("inspection call requires continuation identifiers")
    args = json.loads(call.get("arguments", ""))
    if not isinstance(args, dict) or set(args) != {"box", "label", "rotation"}:
        raise ValueError("inspection requires box, label, and rotation")
    box, label = args["box"], args["label"]
    if (not isinstance(box, list) or len(box) != 4
            or any(type(value) is not int or not 0 <= value <= 1000 for value in box)
            or box[0] >= box[2] or box[1] >= box[3]):
        raise ValueError("inspection box must be ordered integer coordinates within 0..1000")
    if not isinstance(label, str) or not label.strip() or len(label) > 80:
        raise ValueError("inspection label must be nonempty and at most 80 characters")
    if type(args["rotation"]) is not int or args["rotation"] not in {0, 90, 180, 270}:
        raise ValueError("inspection rotation must be 0, 90, 180, or 270 degrees clockwise")
    return {"call_id": call["call_id"], "box": box, "label": label.strip(), "rotation": args["rotation"]}


def render_inspection(image_path: str | Path, call: dict, directory: Path, index: int) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as source:
        clean = source.convert("RGB")
    x0, y0, x1, y1 = call["box"]
    box = (math.floor(x0 * clean.width / 1000), math.floor(y0 * clean.height / 1000),
           math.ceil(x1 * clean.width / 1000), math.ceil(y1 * clean.height / 1000))
    marked = clean.copy()
    ImageDraw.Draw(marked).rectangle((box[0], box[1], box[2] - 1, box[3] - 1), outline="#ff3366", width=max(2, round(max(clean.size) / 120)))
    marked_path, detail_path = (directory / f"{index}-{kind}.png" for kind in ("marked", "detail"))
    marked.save(marked_path)
    detail = clean.crop(box).rotate(-call["rotation"], expand=True)
    scale = min(4, max(1, 1280 / max(detail.size)))
    if scale > 1:
        detail = detail.resize((round(detail.width * scale), round(detail.height * scale)), Image.Resampling.LANCZOS)
    detail.save(detail_path)
    return marked_path, detail_path
