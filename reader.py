"""
Capture a screen region (X11) and read a number from it via OCR.
"""
from __future__ import annotations

import re
from typing import Optional

import mss
import mss.tools
from PIL import Image
import pytesseract


def capture_region(left: int, top: int, width: int, height: int) -> Image.Image:
    """Capture a region of the screen. Returns PIL Image (RGB)."""
    with mss.mss() as sct:
        mon = {"left": left, "top": top, "width": width, "height": height}
        raw = sct.grab(mon)
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


# Tesseract reads digits better when text height is at least ~80px; don't over-scale or text blurs
TARGET_MIN_WIDTH = 180
TARGET_MIN_HEIGHT = 80
MAX_SCALE = 2.5


def _preprocess_simple(img: Image.Image) -> Image.Image:
    """Grayscale; scale up only enough so small text (e.g. '50') is readable, cap scale to avoid blur."""
    w, h = img.size
    if w >= TARGET_MIN_WIDTH and h >= TARGET_MIN_HEIGHT:
        return img.convert("L")
    scale = min(
        MAX_SCALE,
        max(TARGET_MIN_WIDTH / w, TARGET_MIN_HEIGHT / h, 1.0),
    )
    nw = max(TARGET_MIN_WIDTH, int(w * scale))
    nh = max(TARGET_MIN_HEIGHT, int(h * scale))
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    return img.convert("L")


def image_to_number(img: Image.Image) -> Optional[float]:
    """
    Run OCR on image and extract a single number (integer or decimal).
    Returns None if no number found or parse fails.
    """
    proc = _preprocess_simple(img)
    for psm in (6, 7, 3):
        text = pytesseract.image_to_string(proc, config=f"--psm {psm}")
        match = re.search(r"-?\d+(?:[.,]\d+)?", text.replace(",", "."))
        if match:
            try:
                return float(match.group())
            except ValueError:
                pass
    return None


def test_region(
    region: tuple[int, int, int, int],
    save_path: str = "debug_capture.png",
    save_preprocessed_path: str | None = "debug_preprocessed.png",
) -> tuple[str, Optional[float], str]:
    """
    Capture region, save images, run OCR. Returns (raw_ocr_text, extracted_number, image_path).
    Single simple path: grayscale (scale only if tiny), Tesseract PSM 6. No encoding tricks.
    """
    left, top, width, height = region
    img = capture_region(left, top, width, height)
    img.save(save_path)

    proc = _preprocess_simple(img.copy())
    if save_preprocessed_path:
        proc.save(save_preprocessed_path)

    num = image_to_number(img)
    raw_text = pytesseract.image_to_string(proc, config="--psm 6").strip()
    raw_text = raw_text or "(no text detected)"

    return raw_text, num, save_path
