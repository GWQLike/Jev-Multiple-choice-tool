"""Explicit diagnostics; this command may print OCR text to the terminal."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Running ``python tools\\diagnose.py`` puts only tools/ on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from logging_utils import configure_logging
from ocr_engine import OCREngine


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path, help="Path to a screenshot to OCR")
    args = parser.parse_args()
    config = load_config()
    configure_logging(
        Path(__file__).resolve().parents[1] / "logs",
        debug=True,
        api_key=config.typesafe_api_key,
    )
    import numpy as np
    from PIL import Image

    image = np.asarray(Image.open(args.image).convert("RGB"))[:, :, ::-1].copy()
    started = time.perf_counter()
    result = OCREngine().recognize(image)
    print(result.text)
    print(f"OCR: {(time.perf_counter() - started) * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
