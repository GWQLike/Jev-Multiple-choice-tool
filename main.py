"""Background entry point for the Jev single-choice helper."""

from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

from capture import MSSCapture, RegionSelector, crop_image
from config import Config, load_config
from hotkeys import HotkeyState, canonical_key, parse_hotkey
from jev_client import JevClient
from logging_utils import configure_logging
from models import AppError, CaptureRegion, Timings
from ocr_engine import OCREngine
from parser import parse_question
from popup import Popup
from windows_utils import enable_dpi_awareness, monitor_at_cursor

_LOG = logging.getLogger(__name__)


@dataclass
class SelectionRequest:
    image: object
    monitor: CaptureRegion
    completed: threading.Event
    region: CaptureRegion | None = None


@dataclass
class UiMessage:
    kind: str
    value: object
    region: CaptureRegion | None = None
    timings: Timings | None = None


class App:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.work: queue.Queue[str] = queue.Queue()
        self.ui: queue.Queue[SelectionRequest | UiMessage] = queue.Queue()
        self.busy = threading.Lock()
        self.selector: RegionSelector | None = None
        self.listener = None
        self.worker_error: BaseException | None = None
        self.worker = threading.Thread(
            target=self._worker_main, name="jev-worker", daemon=False
        )
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.protocol("WM_DELETE_WINDOW", self.request_stop)
        self.popup = Popup(
            self.root, config.popup_duration_ms, config.confidence_warning_threshold
        )
        self.selector = RegionSelector(self.root)

    def start(self) -> None:
        self.worker.start()
        self.root.after(20, self._poll_startup)
        self.root.after(15, self._poll_ui)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            # Ctrl+C is useful when launched from a console; finish the same
            # orderly shutdown used by the configured exit chord.
            self.request_stop()
            self.root.mainloop()

    def _poll_startup(self) -> None:
        if self.stop_event.is_set():
            return
        if not self.ready_event.is_set():
            self.root.after(50, self._poll_startup)
            return
        if self.worker_error is not None:
            _LOG.error("Worker initialization failed: %s", self.worker_error)
            self.popup.show_error(getattr(self.worker_error, "code", "INTERNAL ERROR"))
            self.root.after(1800, self.request_stop)
            return
        self._start_listener()
        _LOG.info(
            "Ready. Answer=%s Exit=%s Mode=%s",
            self.config.hotkey,
            self.config.exit_hotkey,
            self.config.capture_mode,
        )

    def _start_listener(self) -> None:
        from pynput import keyboard

        state = HotkeyState(
            parse_hotkey(self.config.hotkey), parse_hotkey(self.config.exit_hotkey)
        )

        def on_press(key: object) -> None:
            try:
                action = state.press(canonical_key(key))
                # If answer is a prefix of exit (Alt+Q / Alt+Shift+Q), the
                # answer is still accepted when its last key is pressed. A
                # user who intends exit should press Shift before Q.
                if action == "exit":
                    self.root.after(0, self.request_stop)
                elif action == "answer":
                    self._enqueue_answer()
            except Exception:
                _LOG.exception("Keyboard callback failed")

        def on_release(key: object) -> None:
            try:
                state.release(canonical_key(key))
            except Exception:
                _LOG.exception("Keyboard release callback failed")

        self.listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.daemon = True
        self.listener.start()

    def _enqueue_answer(self) -> None:
        if self.stop_event.is_set() or not self.busy.acquire(blocking=False):
            return
        try:
            self.work.put_nowait("answer")
        except Exception:
            self.busy.release()
            _LOG.exception("Could not queue answer task")

    def _worker_main(self) -> None:
        capture = None
        client = None
        try:
            capture = MSSCapture()
            ocr = OCREngine()
            client = JevClient(
                self.config.typesafe_api_key,
                timeout_seconds=self.config.jev_timeout_seconds,
                model=self.config.jev_model,
            )
            self.ready_event.set()
            while not self.stop_event.is_set():
                try:
                    task = self.work.get(timeout=0.1)
                except queue.Empty:
                    continue
                if task == "stop":
                    break
                if task == "answer":
                    try:
                        self._answer_once(capture, ocr, client)
                    except Exception:
                        _LOG.exception("Unhandled answer task failure")
                        self.ui.put(UiMessage("error", "INTERNAL ERROR"))
                    finally:
                        self.busy.release()
        except BaseException as exc:
            self.worker_error = exc
            self.ready_event.set()
            _LOG.error("Worker startup failed: %s", exc)
        finally:
            if client is not None:
                client.close()
            if capture is not None:
                capture.close()

    def _answer_once(
        self, capture: MSSCapture, ocr: OCREngine, client: JevClient
    ) -> None:
        started = time.perf_counter()
        timings = Timings()
        region: CaptureRegion | None = None
        try:
            # The previous result may overlap the configured capture area. Ask
            # Tk to hide it and wait for acknowledgement before touching MSS.
            hide_done = threading.Event()
            self.ui.put(UiMessage("hide", hide_done))
            while not hide_done.wait(0.02):
                if self.stop_event.is_set():
                    return
            if self.config.capture_mode == "fixed":
                region = self.config.capture_region
                capture_started = time.perf_counter()
                image = capture.grab(region)
                timings.capture_ms = (time.perf_counter() - capture_started) * 1000
            else:
                monitor = monitor_at_cursor()
                capture_started = time.perf_counter()
                image = capture.grab(monitor)
                timings.capture_ms = (time.perf_counter() - capture_started) * 1000
                request = SelectionRequest(image, monitor, threading.Event())
                self.ui.put(request)
                selection_started = time.perf_counter()
                while not request.completed.wait(0.05):
                    if self.stop_event.is_set():
                        return
                timings.selection_ms = (time.perf_counter() - selection_started) * 1000
                region = request.region
                if region is None:
                    return
                image = crop_image(image, monitor, region)

            phase = time.perf_counter()
            ocr_result = ocr.recognize(image)
            timings.ocr_ms = (time.perf_counter() - phase) * 1000
            if self.config.debug:
                _LOG.debug("OCR produced %d lines", len(ocr_result.lines))
            phase = time.perf_counter()
            question = parse_question(ocr_result.text)
            timings.parse_ms = (time.perf_counter() - phase) * 1000
            phase = time.perf_counter()
            answer = client.answer(question)
            timings.jev_ms = (time.perf_counter() - phase) * 1000
            timings.total_ms = (time.perf_counter() - started) * 1000
            self.ui.put(UiMessage("answer", answer, region, timings))
            if self.config.debug:
                _LOG.debug(
                    "Capture: %.0f ms OCR: %.0f ms Parse: %.0f ms Jev: %.0f ms Total: %.0f ms",
                    timings.capture_ms,
                    timings.ocr_ms,
                    timings.parse_ms,
                    timings.jev_ms,
                    timings.total_ms,
                )
        except AppError as exc:
            timings.total_ms = (time.perf_counter() - started) * 1000
            _LOG.warning(
                "Answer task failed: code=%s detail=%s total_ms=%.0f",
                exc.code,
                exc,
                timings.total_ms,
            )
            self.ui.put(UiMessage("error", exc.code, region, timings))
        except Exception:
            _LOG.exception("Answer pipeline failed")
            self.ui.put(UiMessage("error", "INTERNAL ERROR", region, timings))

    def _poll_ui(self) -> None:
        try:
            while True:
                message = self.ui.get_nowait()
                if isinstance(message, SelectionRequest):
                    if self.stop_event.is_set() or self.selector is None:
                        message.completed.set()
                        continue
                    try:
                        self.selector.start(
                            message.image,
                            message.monitor,
                            lambda region, req=message: self._selection_done(
                                req, region
                            ),
                        )
                    except Exception:
                        _LOG.exception("Could not show region selector")
                        message.completed.set()
                    continue
                if message.kind == "hide":
                    self.popup.hide()
                    if isinstance(message.value, threading.Event):
                        message.value.set()
                    continue
                if message.kind == "answer":
                    self.popup.show_answer(
                        message.value,
                        message.timings.total_ms if message.timings else 0,
                        message.region,
                    )
                else:
                    self.popup.show_error(str(message.value), message.region)
        except queue.Empty:
            pass
        if not self.stop_event.is_set():
            self.root.after(15, self._poll_ui)

    @staticmethod
    def _selection_done(
        request: SelectionRequest, region: CaptureRegion | None
    ) -> None:
        request.region = region
        request.completed.set()

    def request_stop(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        if self.listener is not None:
            self.listener.stop()
        if self.selector is not None:
            self.selector.cancel()
        self.work.put_nowait("stop")
        self.popup.hide()
        self.root.after(30, self._finish_stop)

    def _finish_stop(self) -> None:
        if self.worker.is_alive():
            self.root.after(30, self._finish_stop)
            return
        if self.selector is not None:
            self.selector.close()
        self.popup.close()
        self.root.destroy()


def run() -> int:
    enable_dpi_awareness()
    try:
        config = load_config()
    except AppError as exc:
        print(f"{exc.code}: {exc}")
        return 2
    configure_logging(
        Path(__file__).resolve().parent / "logs",
        debug=config.debug,
        api_key=config.typesafe_api_key,
    )
    try:
        App(config).start()
    except Exception:
        _LOG.exception("Application failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
