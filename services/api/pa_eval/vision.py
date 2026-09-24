"""Conservative local localization and cross-view registration for PA patterns."""

from __future__ import annotations

import hashlib
import io
from functools import lru_cache
from pathlib import Path

import cv2  # ty: ignore[unresolved-import]
import numpy as np
from PIL import Image, ImageOps


_ANALYSIS_EDGE = 1000


def _oriented_rgb(path: str | Path) -> Image.Image:
    with Image.open(path) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def _analysis_image(path: str | Path) -> tuple[np.ndarray, float]:
    image = np.asarray(_oriented_rgb(path))
    scale = _ANALYSIS_EDGE / max(image.shape[:2])
    return cv2.resize(image, None, fx=scale, fy=scale), scale


def _plastic_mask(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    return np.asarray((hsv[:, :, 1] < 70) & (hsv[:, :, 2] > 100), dtype=np.uint8) * 255


def _components(mask: np.ndarray, kernel: tuple[int, int]) -> list[tuple[int, int, int, int, int]]:
    opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, kernel))
    _, _, stats, _ = cv2.connectedComponentsWithStats(opened)
    return [(int(row[0]), int(row[1]), int(row[2]), int(row[3]), int(row[4])) for row in stats[1:]]


def _overview_boxes(image: np.ndarray) -> list[tuple[int, int, int, int, float]]:
    height, width = image.shape[:2]
    bars = []
    for x, y, w, h, area in _components(_plastic_mask(image), (40, 12)):
        if w < 0.17 * width or w / max(h, 1) < 2.5 or area < 3000:
            continue
        if h > 0.14 * height or h < 0.04 * height:
            continue
        bars.append((x, y, w, h, area))
    result = []
    for x, y, w, h, area in bars:
        top = max(0, round(y - 0.66 * w))
        bottom = min(height, y + h + 3)
        if bottom - top < 0.15 * height:
            continue
        result.append((max(0, x - 3), top, min(width, x + w + 3), bottom, 0.75))
    for first in range(len(result)):
        for second in range(first + 1, len(result)):
            upper, lower = sorted((first, second), key=lambda index: (result[index][1] + result[index][3]) / 2)
            a, b = result[upper], result[lower]
            horizontal_overlap = min(a[2], b[2]) - max(a[0], b[0])
            if horizontal_overlap < 0.5 * min(a[2] - a[0], b[2] - b[0]) or a[3] <= b[1]:
                continue
            boundary = round((a[3] + b[1]) / 2)
            result[upper] = (a[0], a[1], a[2], boundary - 10, a[4])
            result[lower] = (b[0], boundary + 10, b[2], b[3], b[4])
    for first in range(len(result)):
        for second in range(first + 1, len(result)):
            left, right = sorted((first, second), key=lambda index: (result[index][0] + result[index][2]) / 2)
            a, b = result[left], result[right]
            vertical_overlap = min(a[3], b[3]) - max(a[1], b[1])
            if vertical_overlap < 0.8 * min(a[3] - a[1], b[3] - b[1]):
                continue
            if abs(a[2] - b[0]) > 0.03 * min(a[2] - a[0], b[2] - b[0]):
                continue
            boundary = round((a[2] + b[0]) / 2)
            result[left] = (a[0], a[1], boundary - 3, a[3], a[4])
            result[right] = (boundary + 3, b[1], b[2], b[3], b[4])
    return result


def _detail_boxes(image: np.ndarray) -> list[tuple[int, int, int, int, float]]:
    height, width = image.shape[:2]
    mask = _plastic_mask(image)
    broad_components = _components(mask, (50, 4))
    bars = []
    for x, y, w, h, area in _components(mask, (12, 40)):
        if x < 0.3 * width or h < 0.5 * height or w < 0.09 * width:
            continue
        if h / max(w, 1) < 2.4 or area < 5000:
            continue
        containing = [
            (cx, cy, cw, ch, component_area)
            for cx, cy, cw, ch, component_area in broad_components
            if cx <= x and cx + cw >= x + 0.5 * w
            and abs(cy - y) < 0.1 * height and ch > 0.5 * h
        ]
        containing.sort(key=lambda component: component[4], reverse=True)
        if containing and containing[0][0] > 0.02 * width and containing[0][2] < 0.85 * width:
            left = containing[0][0] + 15
        else:
            left = round(x - 1.8 * w)
        left = max(0, left)
        right = min(width, x + w - 20)
        if right - left < 0.35 * width:
            continue
        bars.append((left, max(0, y - 5), right, min(height, y + h + 5), area))
    if not bars:
        return []
    bars.sort(key=lambda item: item[4], reverse=True)
    left, top, right, bottom, _ = bars[0]
    return [(left, top, right, bottom, 0.65)]


def _png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _validate_bbox(bbox: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = map(int, bbox)
    if not (0 <= left < right <= size[0] and 0 <= top < bottom <= size[1]):
        raise ValueError(f"bbox {bbox} lies outside oriented image {size}")
    return left, top, right, bottom


def locate_regions(image_path: str | Path) -> list[dict]:
    """Find complete patterns; return bboxes in EXIF-oriented source pixels.

    Empty output means localization failed. No full-image substitute is made.
    """
    source = _oriented_rgb(image_path)
    analysis, scale = _analysis_image(image_path)
    candidates = _overview_boxes(analysis) if source.width > source.height else _detail_boxes(analysis)
    regions = []
    for left, top, right, bottom, confidence in candidates:
        bbox = (
            max(0, round(left / scale)),
            max(0, round(top / scale)),
            min(source.width, round(right / scale)),
            min(source.height, round(bottom / scale)),
        )
        if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            continue
        crop = source.crop(bbox)
        regions.append({"bbox": bbox, "confidence": confidence, "crop_sha256": hashlib.sha256(_png_bytes(crop)).hexdigest()})
    return sorted(regions, key=lambda item: (item["bbox"][1], item["bbox"][0]))


def crop_region(image_path: str | Path, bbox: tuple[int, int, int, int], output_path: str | Path) -> dict:
    """Write an unmodified oriented pixel crop as PNG and return provenance."""
    source = _oriented_rgb(image_path)
    box = _validate_bbox(bbox, source.size)
    data = _png_bytes(source.crop(box))
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {
        "bbox": box,
        "source_sha256": hashlib.sha256(Path(image_path).read_bytes()).hexdigest(),
        "crop_sha256": hashlib.sha256(data).hexdigest(),
        "crop_path": str(target),
    }


@lru_cache(maxsize=24)
def _cached_features(path: str, mtime_ns: int, size: int) -> tuple[list, np.ndarray | None, float]:
    del mtime_ns, size
    image = _oriented_rgb(path)
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    scale = 1600 / max(gray.shape)
    gray = cv2.resize(gray, None, fx=scale, fy=scale)
    keypoints, descriptors = cv2.SIFT_create(nfeatures=6000).detectAndCompute(gray, None)
    return keypoints, descriptors, scale


def _features(path: str | Path) -> tuple[list, np.ndarray | None, float]:
    source = Path(path)
    stat = source.stat()
    return _cached_features(str(source.resolve()), stat.st_mtime_ns, stat.st_size)


def _intersection_over_union(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return overlap / (area_a + area_b - overlap) if area_a + area_b > overlap else 0.0


def match_regions(
    overview_path: str | Path,
    overview_bbox: tuple[int, int, int, int],
    detail_path: str | Path,
    detail_bbox: tuple[int, int, int, int],
) -> dict:
    """Register detail to overview; uncertain evidence never establishes identity."""
    overview_image = _oriented_rgb(overview_path)
    detail_image = _oriented_rgb(detail_path)
    overview_box = _validate_bbox(overview_bbox, overview_image.size)
    detail_box = _validate_bbox(detail_bbox, detail_image.size)
    if hashlib.sha256(Path(overview_path).read_bytes()).digest() == hashlib.sha256(Path(detail_path).read_bytes()).digest():
        return {"status": "uncertain", "score": 0.0, "provenance": {"reason": "identical_source_image"}}
    overview_points, overview_desc, overview_scale = _features(overview_path)
    detail_points, detail_desc, detail_scale = _features(detail_path)
    if overview_desc is None or detail_desc is None:
        return {"status": "uncertain", "score": 0.0, "provenance": {"reason": "insufficient_features"}}
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(detail_desc, overview_desc, k=2)
    good = [first for first, second in pairs if first.distance < 0.7 * second.distance]
    if len(good) < 12:
        return {"status": "uncertain", "score": 0.0, "provenance": {"reason": "insufficient_unique_matches", "feature_matches": len(good)}}
    source = np.asarray([detail_points[m.queryIdx].pt for m in good], dtype=np.float32)
    target = np.asarray([overview_points[m.trainIdx].pt for m in good], dtype=np.float32)
    transform, mask = cv2.findHomography(source, target, cv2.RANSAC, 4)
    if transform is None or mask is None:
        return {"status": "uncertain", "score": 0.0, "provenance": {"reason": "registration_failed"}}
    inliers = int(mask.sum())
    corners = np.asarray([
        [detail_box[0] * detail_scale, detail_box[1] * detail_scale],
        [detail_box[2] * detail_scale, detail_box[1] * detail_scale],
        [detail_box[2] * detail_scale, detail_box[3] * detail_scale],
        [detail_box[0] * detail_scale, detail_box[3] * detail_scale],
    ], dtype=np.float32).reshape(-1, 1, 2)
    projected = cv2.perspectiveTransform(corners, transform).reshape(-1, 2) / overview_scale
    projected_box = (float(projected[:, 0].min()), float(projected[:, 1].min()), float(projected[:, 0].max()), float(projected[:, 1].max()))
    overlap = _intersection_over_union(projected_box, overview_box)
    score = round(float(overlap), 3)
    provenance = {"method": "sift_ransac_homography", "feature_matches": len(good), "inliers": inliers, "projected_bbox": [round(value, 1) for value in projected_box], "iou": score}
    if inliers < 14 or inliers / len(good) < 0.18:
        provenance["reason"] = "weak_registration"
        return {"status": "uncertain", "score": score, "provenance": provenance}
    if overlap < 0.35:
        provenance["reason"] = "region_overlap_too_small"
        return {"status": "uncertain", "score": score, "provenance": provenance}
    return {"status": "matched", "score": score, "provenance": provenance}
