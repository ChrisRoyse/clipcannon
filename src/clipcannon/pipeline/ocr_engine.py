"""Region/font classification helpers and the PaddleOCR frame runner."""

from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _classify_region_from_relative_y(relative_y: float) -> str:
    """Classify text region based on relative vertical position.

    Args:
        relative_y: Y-center position as fraction of image height (0.0-1.0).

    Returns:
        Region classification string.
    """
    if relative_y < 0.25:
        return "center_top"
    if relative_y < 0.67:
        return "center_middle"
    if relative_y < 0.85:
        return "bottom_third"
    return "full_screen"


def _estimate_font_size_from_height(relative_height: float) -> str:
    """Estimate font size category from relative bounding box height.

    Args:
        relative_height: Bbox height as fraction of image height (0.0-1.0).

    Returns:
        Font size classification: "small", "medium", or "large".
    """
    if relative_height < 0.03:
        return "small"
    if relative_height < 0.08:
        return "medium"
    return "large"


def _classify_region(
    bbox: list[list[float]],
    img_width: int,
    img_height: int,
) -> str:
    """Classify text region based on bounding box position.

    Args:
        bbox: Bounding box as list of 4 corner points [[x,y], ...].
        img_width: Image width in pixels.
        img_height: Image height in pixels.

    Returns:
        Region classification string.
    """
    if not bbox or len(bbox) < 4:
        return "unknown"

    y_coords = [pt[1] for pt in bbox]
    y_center = sum(y_coords) / len(y_coords)
    relative_y = y_center / img_height if img_height > 0 else 0.5

    return _classify_region_from_relative_y(relative_y)


def _estimate_font_size(bbox: list[list[float]], img_height: int) -> str:
    """Estimate font size category from bounding box height.

    Args:
        bbox: Bounding box as list of 4 corner points.
        img_height: Image height in pixels.

    Returns:
        Font size classification: "small", "medium", or "large".
    """
    if not bbox or len(bbox) < 4:
        return "medium"

    y_coords = [pt[1] for pt in bbox]
    bbox_height = max(y_coords) - min(y_coords)
    relative_height = bbox_height / img_height if img_height > 0 else 0.0

    return _estimate_font_size_from_height(relative_height)


def _texts_differ_significantly(
    prev_texts: list[str],
    curr_texts: list[str],
) -> bool:
    """Check if text content changed significantly between frames.

    Args:
        prev_texts: Previous frame text list.
        curr_texts: Current frame text list.

    Returns:
        True if significant text change detected.
    """
    if not prev_texts and not curr_texts:
        return False
    if not prev_texts or not curr_texts:
        return True

    prev_set = set(prev_texts)
    curr_set = set(curr_texts)
    overlap = prev_set & curr_set
    total = prev_set | curr_set

    if not total:
        return False

    # More than 50% change is significant
    return len(overlap) / len(total) < 0.5


def _run_paddleocr_on_frames(
    frame_paths: list[Path],
    extraction_fps: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Run PaddleOCR PP-OCRv5 on frames via GPU subprocess.

    PaddlePaddle-GPU requires LD_LIBRARY_PATH set before process start
    (CUDA 13.0 libs bundled with pip package). We run OCR in a subprocess
    with the correct library path to get GPU acceleration while keeping
    the main MCP server process stable.

    Args:
        frame_paths: Paths to frames to process (1fps subset).
        extraction_fps: Original frame extraction rate.

    Returns:
        Tuple of (text_records, change_events).

    Raises:
        ImportError: If PaddleOCR is not available.
        RuntimeError: If the OCR subprocess fails.
    """
    import os
    import subprocess
    import site

    from PIL import Image

    # Build the LD_LIBRARY_PATH for PaddlePaddle-GPU
    cu13_lib = os.path.join(site.getsitepackages()[0], "nvidia", "cu13", "lib")
    paddle_env = os.environ.copy()
    paddle_env["LD_LIBRARY_PATH"] = f"{cu13_lib}:{paddle_env.get('LD_LIBRARY_PATH', '')}"
    paddle_env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

    # Write frame paths to a temp file for the subprocess
    frame_list_path = Path(tempfile.mktemp(suffix=".txt"))
    frame_list_path.write_text("\n".join(str(fp) for fp in frame_paths))

    # Build the OCR worker script
    worker_script = f"""
import os, sys, json, time, warnings
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
warnings.filterwarnings('ignore')

from paddleocr import PaddleOCR
from PIL import Image
import tempfile
from pathlib import Path

frame_list = Path('{frame_list_path}').read_text().strip().split('\\n')
extraction_fps = {extraction_fps}
max_ocr_width = 1920

ocr = PaddleOCR(lang='en')

text_records = []
change_events = []
prev_texts = []
total = len(frame_list)

for idx, fp_str in enumerate(frame_list):
    fp = Path(fp_str)
    if idx == 0 or (idx + 1) % 50 == 0:
        print(f'OCR progress: {{idx + 1}}/{{total}}', file=sys.stderr)

    stem = fp.stem
    frame_number = int(stem.split('_')[1])
    ts_ms = int((frame_number - 1) * 1000 / extraction_fps)

    # An unreadable frame fails the stage (#68); skipping it would store an
    # OCR result that silently omits that instant.
    img = Image.open(fp)
    img_w, img_h = img.size

    temp_path = None
    ocr_input = str(fp)
    try:
        if img_w > max_ocr_width:
            scale = max_ocr_width / img_w
            resized = img.resize((max_ocr_width, int(img_h * scale)), Image.LANCZOS)
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                resized.save(tmp.name, 'JPEG', quality=90)
                temp_path = tmp.name
                ocr_input = temp_path

        results = list(ocr.predict(input=ocr_input))
        if not results or not results[0].get('rec_texts'):
            continue

        page = results[0]
        texts_list = page['rec_texts']
        scores_list = page['rec_scores']
        polys_list = page.get('dt_polys', [])

    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)

    curr_texts = []
    entries = []
    for i, (text, conf) in enumerate(zip(texts_list, scores_list)):
        if conf < 0.5:
            continue
        curr_texts.append(text)
        region = 'unknown'
        font_size = 'medium'
        if i < len(polys_list):
            poly = polys_list[i]
            y_coords = [pt[1] for pt in poly]
            y_center = sum(y_coords) / len(y_coords)
            rel_y = y_center / img_h if img_h > 0 else 0.5
            if rel_y < 0.25: region = 'center_top'
            elif rel_y < 0.67: region = 'center_middle'
            elif rel_y < 0.85: region = 'bottom_third'
            else: region = 'full_screen'
            bh = max(y_coords) - min(y_coords)
            rh = bh / img_h if img_h > 0 else 0
            if rh < 0.03: font_size = 'small'
            elif rh < 0.08: font_size = 'medium'
            else: font_size = 'large'
        entries.append({{'text': text, 'confidence': str(round(conf, 3)), 'region': region, 'font_size': font_size}})

    if curr_texts == prev_texts:
        continue

    prev_set = set(prev_texts or [])
    curr_set = set(curr_texts or [])
    overlap = prev_set & curr_set
    total_set = prev_set | curr_set
    changed = (len(overlap) / len(total_set) < 0.5) if total_set else False

    if curr_texts:
        text_records.append({{
            'start_ms': ts_ms,
            'end_ms': ts_ms + int(1000 / extraction_fps),
            'texts': json.dumps(entries),
            'type': 'detected',
            'change_from_previous': changed,
        }})

    if changed and prev_texts:
        change_events.append({{
            'timestamp_ms': ts_ms,
            'type': 'slide_transition',
            'new_title': curr_texts[0] if curr_texts else '',
        }})

    prev_texts = curr_texts

print(json.dumps({{'text_records': text_records, 'change_events': change_events}}))
"""

    logger.info("Starting PaddleOCR subprocess (GPU) for %d frames", len(frame_paths))
    ocr_start = time.monotonic()

    try:
        proc = subprocess.run(
            ["python3", "-c", worker_script],
            env=paddle_env,
            capture_output=True,
            text=True,
            timeout=580,  # Just under the 600s stage timeout
        )
    finally:
        frame_list_path.unlink(missing_ok=True)

    if proc.returncode != 0:
        stderr_tail = proc.stderr[-500:] if proc.stderr else ""
        raise RuntimeError(
            f"PaddleOCR subprocess failed (exit {proc.returncode}): {stderr_tail}"
        )

    # Log progress messages from subprocess stderr
    for line in (proc.stderr or "").strip().split("\n"):
        if line.startswith("OCR progress:"):
            logger.info(line)

    # Parse JSON output
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        stdout_tail = proc.stdout[-200:] if proc.stdout else ""
        raise RuntimeError(
            f"PaddleOCR subprocess returned invalid JSON: {exc}. "
            f"stdout tail: {stdout_tail}"
        ) from exc

    text_records = result.get("text_records", [])
    change_events = result.get("change_events", [])

    ocr_elapsed = time.monotonic() - ocr_start
    logger.info(
        "OCR complete: %d text records, %d events in %.1fs",
        len(text_records),
        len(change_events),
        ocr_elapsed,
    )

    return text_records, change_events
