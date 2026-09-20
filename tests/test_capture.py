"""Capture tests use generated arrays and a fake MSS backend, never the desktop."""

from __future__ import annotations

import threading

import numpy as np
import pytest

import capture
from capture import MSSCapture, crop_image
from models import CaptureError, CaptureRegion


def test_crop_preserves_bgr_and_handles_negative_monitor_origin() -> None:
    image = np.arange(6 * 8 * 3, dtype=np.uint8).reshape(6, 8, 3)
    result = crop_image(
        image, CaptureRegion(-100, -30, 8, 6), CaptureRegion(-98, -29, 4, 3)
    )
    np.testing.assert_array_equal(result, image[1:4, 2:6])
    assert result.flags.c_contiguous


@pytest.mark.parametrize(
    "region",
    [
        CaptureRegion(-1, 0, 3, 2),
        CaptureRegion(0, 0, 9, 2),
        CaptureRegion(0, 0, 0, 2),
        CaptureRegion(0, 0, 2, -1),
    ],
)
def test_crop_rejects_outside_or_empty_regions(region: CaptureRegion) -> None:
    with pytest.raises(CaptureError):
        crop_image(np.zeros((6, 8, 3), np.uint8), CaptureRegion(0, 0, 8, 6), region)


def test_crop_rejects_wrong_shape() -> None:
    with pytest.raises(CaptureError):
        crop_image(
            np.zeros((6, 8, 4), np.uint8),
            CaptureRegion(0, 0, 8, 6),
            CaptureRegion(1, 1, 2, 2),
        )


class FakeMSS:
    def __init__(self) -> None:
        self.monitors = [{"left": -10, "top": 0, "width": 20, "height": 10}]
        self.close_count = 0
        self.calls: list[dict[str, int]] = []

    def grab(self, region: dict[str, int]) -> np.ndarray:
        self.calls.append(region)
        result = np.empty((region["height"], region["width"], 4), np.uint8)
        result[:] = (11, 22, 33, 255)
        return result

    def close(self) -> None:
        self.close_count += 1


def test_capture_reuses_backend_and_returns_contiguous_bgr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeMSS()
    monkeypatch.setattr(capture, "MSS", lambda: backend)
    engine = MSSCapture()
    for _ in range(2):
        image = engine.grab(CaptureRegion(-5, 2, 4, 3))
        assert image.shape == (3, 4, 3)
        assert image.flags.c_contiguous
        np.testing.assert_array_equal(image[0, 0], (11, 22, 33))
    assert len(backend.calls) == 2
    engine.close()
    engine.close()
    assert backend.close_count == 1
    with pytest.raises(CaptureError):
        engine.grab(CaptureRegion(-5, 2, 4, 3))


def test_capture_rejects_outside_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakeMSS()
    monkeypatch.setattr(capture, "MSS", lambda: backend)
    engine = MSSCapture()
    with pytest.raises(CaptureError):
        engine.grab(CaptureRegion(-11, 0, 4, 3))
    assert backend.calls == []
    engine.close()


def test_capture_rejects_other_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capture, "MSS", FakeMSS)
    engine = MSSCapture()
    errors: list[Exception] = []

    def other_thread() -> None:
        try:
            engine.grab(CaptureRegion(0, 0, 2, 2))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=other_thread)
    thread.start()
    thread.join()
    assert len(errors) == 1 and isinstance(errors[0], CaptureError)
    engine.close()
