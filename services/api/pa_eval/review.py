"""Build a local, oriented-image review page for model inspection targets."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


def write_review_page(trials: list[dict[str, Any]], observations: dict[str, dict[str, Any]], output_dir: Path) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    image_dir = output_dir / "review_images"
    for trial in trials:
        target = (trial.get("response") or {}).get("inspection_target")
        if target is None or trial.get("validation_errors"):
            continue
        observation_id = target["observation_id"]
        box = target["box"]
        target_id = hashlib.sha256(
            json.dumps([trial["pattern_id"], trial["step"], observation_id, box, trial.get("response_id")], separators=(",", ":")).encode()
        ).hexdigest()[:16]
        targets.append({
            "target_id": target_id,
            "pattern_id": trial["pattern_id"],
            "step": trial["step"],
            "observation_id": observation_id,
            "source_sha256": observations[observation_id]["sha256"],
            "response_id": trial.get("response_id"),
            "box": box,
            "reason": target["reason"],
            "rating": "unrated",
        })
        image_dir.mkdir(exist_ok=True)
        oriented_path = image_dir / f"{observation_id}.jpg"
        if not oriented_path.exists():
            with Image.open(observations[observation_id]["resolved_path"]) as image:
                oriented = ImageOps.exif_transpose(image)
                oriented.save(oriented_path, quality=95)
    (output_dir / "target_ratings.json").write_text(json.dumps(targets, indent=2) + "\n")
    cards = []
    for target in targets:
        left, top, right, bottom = target["box"]
        overlay = f"left:{left * 100:.4f}%;top:{top * 100:.4f}%;width:{(right-left) * 100:.4f}%;height:{(bottom-top) * 100:.4f}%"
        options = "".join(f'<option value="{value}">{value}</option>' for value in ("unrated", "useful", "unhelpful", "uncertain"))
        cards.append(
            f'<article data-target-id="{target["target_id"]}">'
            f'<h2>{html.escape(target["pattern_id"])} · {html.escape(target["step"])}</h2>'
            f'<p>Observation {html.escape(target["observation_id"])} · {html.escape(target["reason"])}</p>'
            f'<div class="photo"><img src="review_images/{html.escape(target["observation_id"])}.jpg" alt="Oriented observation">'
            f'<div class="box" style="{overlay}"></div></div>'
            f'<label>Usefulness <select aria-label="Rate {target["target_id"]}">{options}</select></label></article>'
        )
    data = json.dumps(targets).replace("<", "\\u003c")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>PA inspection target review</title>
<style>body{{font:16px system-ui;margin:2rem;max-width:1100px}}article{{border:1px solid #bbb;padding:1rem;margin:1rem 0}}.photo{{position:relative;width:min(100%,800px)}}img{{display:block;width:100%}}.box{{position:absolute;border:3px solid #f20;background:#f204;box-sizing:border-box}}select,button{{font:inherit}}</style>
</head><body><h1>Inspection target review</h1><p>Inspect the named physical region. Rate whether a clearer view there could separate the remaining candidates. A usefulness rating is separate from proof that a new view resolved them.</p>
{''.join(cards) if cards else '<p>No valid inspection targets to rate.</p>'}
<button id="download">Download ratings.json</button>
<script>const targets={data};const key='pa-target-ratings-v1';const saved=JSON.parse(localStorage.getItem(key)||'{{}}');
document.querySelectorAll('article').forEach(card=>{{const id=card.dataset.targetId;const select=card.querySelector('select');select.value=saved[id]||'unrated';select.onchange=()=>{{saved[id]=select.value;localStorage.setItem(key,JSON.stringify(saved));}};}});
document.getElementById('download').onclick=()=>{{const rated=targets.map(t=>({{...t,rating:saved[t.target_id]||'unrated'}}));const blob=new Blob([JSON.stringify(rated,null,2)+'\\n'],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='ratings.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}};</script></body></html>"""
    (output_dir / "review.html").write_text(page)
    return targets
