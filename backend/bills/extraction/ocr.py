"""Local OCR: page images and scanned PDFs -> text lines. Nothing leaves the machine.

The lines contain everything printed on the bill, personal information included.
"""

from functools import lru_cache
from pathlib import Path

import numpy as np
import pypdfium2
from PIL import Image

# Boxes whose vertical centres are closer than this (in pixels) share a line.
LINE_TOLERANCE = 12


@lru_cache(maxsize=1)
def _engine():
    # Imported lazily: loading the models takes a few seconds.
    from rapidocr import RapidOCR

    return RapidOCR(params={"Global.log_level": "warning"})  # very chatty at INFO


def pdf_page_images(path: Path, scale: float = 2.0) -> list[Image.Image]:
    pdf = pypdfium2.PdfDocument(str(path))
    try:
        return [page.render(scale=scale).to_pil() for page in pdf]
    finally:
        pdf.close()


def ocr_lines(image: Image.Image) -> list[str]:
    """Text lines of one page image, top to bottom, boxes left to right."""
    output = _engine()(np.array(image.convert("RGB")))
    if output.boxes is None or not len(output.txts):
        return []
    result = list(zip(output.boxes.tolist(), output.txts, output.scores))
    # Phone photos are a little rotated: estimate the skew from the slope of
    # the text boxes' top edges and straighten the y coordinates, otherwise a
    # label and its amount at the far right end up on different lines.
    slope = float(np.median([
        (p[1][1] - p[0][1]) / (p[1][0] - p[0][0])
        for p, _, _ in result
        if p[1][0] - p[0][0] > 20
    ] or [0.0]))
    boxes = []
    for points, text, _score in result:
        x = min(p[0] for p in points)
        y = sum(p[1] for p in points) / len(points) - slope * x
        boxes.append((y, x, text))
    boxes.sort()

    lines, current, current_y = [], [], None
    for y, x, text in boxes:
        if current_y is not None and y - current_y > LINE_TOLERANCE:
            lines.append(" ".join(t for _, t in sorted(current)))
            current = []
        if not current:
            current_y = y
        current.append((x, text))
    if current:
        lines.append(" ".join(t for _, t in sorted(current)))
    return lines
