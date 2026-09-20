"""The application's small, reusable, non-activating result window."""

from __future__ import annotations

import tkinter as tk

from models import Answer, CaptureRegion
from windows_utils import (
    configure_tool_window,
    dpi_for_window,
    position_window,
    show_without_activation,
    work_area_for_region,
)


class Popup:
    def __init__(self, root: tk.Tk, duration_ms: int, warning_threshold: float) -> None:
        self._root = root
        self._duration_ms = duration_ms
        self._warning_threshold = warning_threshold
        self._timer: str | None = None
        self._closed = False
        self._window = tk.Toplevel(root, bg="#111827")
        self._window.withdraw()
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)
        self._answer = tk.Label(
            self._window, bg="#111827", fg="#f8fafc", takefocus=False
        )
        self._detail = tk.Label(
            self._window, bg="#111827", fg="#94a3b8", takefocus=False
        )
        self._answer.pack(fill="x", expand=True)
        self._detail.pack(fill="x", pady=(0, 14))

    def show_answer(
        self, answer: Answer, total_ms: float, region: CaptureRegion | None = None
    ) -> None:
        uncertain = answer.confidence < self._warning_threshold
        self._show(
            answer.answer + (" ?" if uncertain else ""),
            f"{answer.confidence:.1%} · {total_ms:.0f}ms",
            region,
            error=False,
            uncertain=uncertain,
        )

    def show_error(self, code: str, region: CaptureRegion | None = None) -> None:
        self._show(code, "", region, error=True, uncertain=False)

    def _show(
        self,
        text: str,
        detail: str,
        region: CaptureRegion | None,
        *,
        error: bool,
        uncertain: bool,
    ) -> None:
        if self._closed:
            return
        self.hide()
        area = work_area_for_region(region)
        self._answer.configure(
            text=text, fg="#fbbf24" if uncertain or error else "#f8fafc"
        )
        self._detail.configure(text=detail)
        # Move while hidden first so GetDpiForWindow sees the destination monitor.
        self._window.update_idletasks()
        configure_tool_window(self._window, no_activate=True)
        position_window(
            self._window,
            CaptureRegion(area.left, area.top, 240, 136),
            no_activate=True,
            show=False,
        )
        scale = dpi_for_window(self._window) / 96.0
        width = min(round((290 if error else 240) * scale), area.width)
        height = min(round(136 * scale), area.height)
        padding = round(24 * scale)
        self._answer.configure(
            font=("Segoe UI", -round((22 if error else 58) * scale), "bold")
        )
        self._detail.configure(font=("Segoe UI", -round(13 * scale)))
        self._detail.pack_configure(pady=(0, round(16 * scale)))
        target = CaptureRegion(
            max(area.left, area.left + area.width - width - padding),
            max(area.top, area.top + area.height - height - padding),
            width,
            height,
        )
        self._window.geometry(f"{width}x{height}+{target.left}+{target.top}")
        self._window.update_idletasks()
        configure_tool_window(self._window, no_activate=True)
        self._window.deiconify()
        show_without_activation(self._window)
        position_window(self._window, target, no_activate=True)
        self._timer = self._root.after(self._duration_ms, self.hide)

    def hide(self) -> None:
        if self._closed:
            return
        if self._timer is not None:
            self._root.after_cancel(self._timer)
            self._timer = None
        self._window.withdraw()

    def close(self) -> None:
        if not self._closed:
            self.hide()
            self._closed = True
            self._window.destroy()
