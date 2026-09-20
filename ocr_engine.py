"""One reusable ONNX OCR engine, returning text and geometric line information."""

from __future__ import annotations

from pathlib import Path
from statistics import median

import numpy as np
from numpy.typing import NDArray

from models import OCRError, OCRLine, OCRResult


def arrange_lines(lines: list[OCRLine]) -> OCRResult:
    if not lines:
        raise OCRError("No text found in the captured region.")

    # Compare box centers, not exact y coordinates: OCR boxes on one row differ slightly.
    def bounds(line: OCRLine) -> tuple[float, float, float, float]:
        xs, ys = zip(*line.box)
        return min(xs), min(ys), max(xs), max(ys)

    ordered = sorted(lines, key=lambda line: (bounds(line)[1], bounds(line)[0]))
    rows: list[list[OCRLine]] = []
    for line in ordered:
        left, top, right, bottom = bounds(line)
        center = (top + bottom) / 2
        if rows:
            previous = rows[-1]
            boxes = [bounds(item) for item in previous]
            row_center = median((box[1] + box[3]) / 2 for box in boxes)
            row_height = median(box[3] - box[1] for box in boxes)
            if abs(center - row_center) <= 0.45 * min(bottom - top, row_height):
                previous.append(line)
                continue
        rows.append([line])
    result: list[OCRLine] = []
    for row in rows:
        row.sort(key=lambda line: bounds(line)[0])
        boxes = [bounds(line) for line in row]
        left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
        right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
        result.append(
            OCRLine(
                text=" ".join(line.text.strip() for line in row),
                box=((left, top), (right, top), (right, bottom), (left, bottom)),
                confidence=min(line.confidence for line in row),
            )
        )
    return OCRResult("\n".join(line.text for line in result), tuple(result))


class OCREngine:
    def __init__(self, model_dir: Path | None = None) -> None:
        from rapidocr import (
            EngineType,
            LangDet,
            LangRec,
            ModelType,
            OCRVersion,
            RapidOCR,
        )

        folder = model_dir or Path(__file__).resolve().parent / ".models"
        folder.mkdir(parents=True, exist_ok=True)
        params = {
            "Global.model_root_dir": str(folder),
            "Global.use_cls": False,
            "Global.log_level": "error",
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Det.lang_type": LangDet.CH,
            "Det.model_type": ModelType.MOBILE,
            "Det.ocr_version": OCRVersion.PPOCRV4,
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Rec.lang_type": LangRec.CH,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV4,
        }
        try:
            self._engine = RapidOCR(params=params)
            # Warm both inference paths even if the blank detector finds no text.
            blank = np.full((96, 320, 3), 255, dtype=np.uint8)
            self._engine(blank, use_det=True, use_cls=False, use_rec=True)
            self._engine(blank, use_det=False, use_cls=False, use_rec=True)
        except Exception as exc:
            raise OCRError(
                "OCR initialization failed; check models and ONNX Runtime installation."
            ) from exc

    def recognize(self, image: NDArray[np.uint8]) -> OCRResult:
        if image.ndim != 3 or image.shape[2] != 3 or image.size == 0:
            raise OCRError("OCR requires a nonempty BGR image.")
        try:
            output = self._engine(image, use_det=True, use_cls=False, use_rec=True)
            if output.txts is None or output.boxes is None or output.scores is None:
                raise OCRError("No text found in the captured region.")
            lines = [
                OCRLine(
                    text.strip(),
                    tuple((float(x), float(y)) for x, y in box),
                    float(score),
                )
                for text, box, score in zip(
                    output.txts, output.boxes, output.scores, strict=True
                )
                if text.strip()
            ]
            return arrange_lines(lines)
        except OCRError:
            raise
        except Exception as exc:
            raise OCRError("OCR inference failed.") from exc
