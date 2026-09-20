"""In-memory screenshots and a temporary, frozen-screen region selector."""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable

import numpy as np
from mss import MSS
from PIL import Image, ImageTk

from models import CaptureError, CaptureRegion
from windows_utils import configure_tool_window, position_window


def _validate_region(region: CaptureRegion) -> None:
    if region.width <= 0 or region.height <= 0:
        raise CaptureError("Capture width and height must be positive.")


def _contains(outer: CaptureRegion, inner: CaptureRegion) -> bool:
    return (
        inner.left >= outer.left
        and inner.top >= outer.top
        and inner.left + inner.width <= outer.left + outer.width
        and inner.top + inner.height <= outer.top + outer.height
    )


def _validate_image(image: np.ndarray, region: CaptureRegion) -> None:
    if image.dtype != np.uint8 or image.shape != (region.height, region.width, 3):
        raise CaptureError("Expected a uint8 BGR image matching the capture region.")


def crop_image(
    image_bgr: np.ndarray, source: CaptureRegion, region: CaptureRegion
) -> np.ndarray:
    """Crop a frozen capture using global physical coordinates; never recapture UI."""
    _validate_region(source)
    _validate_region(region)
    _validate_image(image_bgr, source)
    if not _contains(source, region):
        raise CaptureError("The selected region is outside the frozen screenshot.")
    x = region.left - source.left
    y = region.top - source.top
    return np.ascontiguousarray(image_bgr[y : y + region.height, x : x + region.width])


class MSSCapture:
    """Create, reuse, and close on the application's single worker thread."""

    def __init__(self) -> None:
        self._owner_thread = threading.get_ident()
        self._closed = False
        try:
            self._capture = MSS()
        except Exception as exc:
            raise CaptureError("Could not initialize screen capture.") from exc

    def _check_thread(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise CaptureError("MSSCapture must be used on its creating thread.")

    def grab(self, region: CaptureRegion) -> np.ndarray:
        self._check_thread()
        if self._closed:
            raise CaptureError("Screen capture is already closed.")
        _validate_region(region)
        try:
            desktop = CaptureRegion(
                **{
                    key: self._capture.monitors[0][key]
                    for key in ("left", "top", "width", "height")
                }
            )
            if not _contains(desktop, region):
                raise CaptureError(
                    "The configured region extends outside the virtual desktop."
                )
            shot = self._capture.grab(region.as_dict())
            # MSS exposes BGRA directly: one contiguous BGR copy is all OCR needs.
            return np.ascontiguousarray(np.asarray(shot, dtype=np.uint8)[:, :, :3])
        except CaptureError:
            raise
        except Exception as exc:
            raise CaptureError(
                "Windows could not capture the requested region."
            ) from exc

    def close(self) -> None:
        self._check_thread()
        if not self._closed:
            self._closed = True
            self._capture.close()


class RegionSelector:
    """A transient selector on one monitor. Every method runs on Tk's thread."""

    def __init__(self, root: tk.Tk) -> None:
        self._window = tk.Toplevel(root)
        self._window.withdraw()
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)
        self._canvas = tk.Canvas(
            self._window, highlightthickness=0, bd=0, cursor="crosshair"
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<ButtonPress-1>", self._press)
        self._canvas.bind("<B1-Motion>", self._motion)
        self._canvas.bind("<ButtonRelease-1>", self._release)
        self._window.bind("<Escape>", lambda _event: self.cancel())
        self._window.bind("<Button-3>", lambda _event: self.cancel())
        self._window.protocol("WM_DELETE_WINDOW", self.cancel)
        self._monitor: CaptureRegion | None = None
        self._on_done: Callable[[CaptureRegion | None], None] | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._start_point: tuple[int, int] | None = None

    @property
    def active(self) -> bool:
        return self._on_done is not None

    def start(
        self,
        image_bgr: np.ndarray,
        monitor: CaptureRegion,
        on_done: Callable[[CaptureRegion | None], None],
    ) -> None:
        if self.active:
            raise CaptureError("A region selection is already active.")
        _validate_region(monitor)
        _validate_image(image_bgr, monitor)
        self._monitor = monitor
        self._on_done = on_done
        self._start_point = None
        try:
            self._photo = ImageTk.PhotoImage(
                Image.fromarray(image_bgr[:, :, ::-1]), master=self._window
            )
            self._canvas.delete("all")
            self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
            self._window.geometry(
                f"{monitor.width}x{monitor.height}+{monitor.left}+{monitor.top}"
            )
            self._window.update_idletasks()
            configure_tool_window(self._window, no_activate=False)
            self._window.deiconify()
            position_window(self._window, monitor, no_activate=False)
            self._window.grab_set()
            self._canvas.focus_force()  # Explicit interactive selection needs Esc input.
        except Exception:
            # The caller owns error reporting; do not also issue a cancellation callback.
            self._on_done = None
            self._clear()
            raise

    def _point(self, event: tk.Event) -> tuple[int, int]:
        assert self._monitor is not None
        return (
            max(0, min(int(event.x), self._monitor.width)),
            max(0, min(int(event.y), self._monitor.height)),
        )

    def _press(self, event: tk.Event) -> None:
        if not self.active:
            return
        self._start_point = self._point(event)
        self._canvas.delete("selection")
        x, y = self._start_point
        self._canvas.create_rectangle(
            x, y, x, y, outline="#38bdf8", width=2, tags="selection"
        )

    def _motion(self, event: tk.Event) -> None:
        if self.active and self._start_point is not None:
            self._canvas.coords("selection", *self._start_point, *self._point(event))

    def _release(self, event: tk.Event) -> None:
        if not self.active or self._start_point is None or self._monitor is None:
            return
        x0, y0 = self._start_point
        x1, y1 = self._point(event)
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        region = None
        if right - left >= 3 and bottom - top >= 3:
            region = CaptureRegion(
                self._monitor.left + left,
                self._monitor.top + top,
                right - left,
                bottom - top,
            )
        self._finish(region)

    def _clear(self) -> None:
        try:
            self._window.grab_release()
            self._window.withdraw()
            self._canvas.delete("all")
        finally:
            self._photo = None
            self._monitor = None
            self._start_point = None

    def _finish(self, region: CaptureRegion | None) -> None:
        callback = self._on_done
        if callback is None:
            return
        self._on_done = None
        self._clear()
        callback(region)

    def cancel(self) -> None:
        self._finish(None)

    def close(self) -> None:
        self.cancel()
        self._window.destroy()
