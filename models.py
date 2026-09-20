"""Small, provider-independent values exchanged by the application."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureRegion:
    left: int
    top: int
    width: int
    height: int

    def as_dict(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class OCRLine:
    text: str
    box: tuple[tuple[float, float], ...]
    confidence: float


@dataclass(frozen=True)
class OCRResult:
    text: str
    lines: tuple[OCRLine, ...]


@dataclass(frozen=True)
class Question:
    question: str
    choices: dict[str, str]


@dataclass(frozen=True)
class Answer:
    answer: str
    confidence: float
    probabilities: dict[str, float]


@dataclass
class Timings:
    capture_ms: float = 0.0
    ocr_ms: float = 0.0
    parse_ms: float = 0.0
    jev_ms: float = 0.0
    total_ms: float = 0.0
    selection_ms: float = 0.0


class AppError(Exception):
    code = "INTERNAL ERROR"


class ConfigError(AppError):
    code = "CONFIG ERROR"


class CaptureError(AppError):
    code = "CAPTURE ERROR"


class OCRError(AppError):
    code = "OCR ERROR"


class ParseError(AppError):
    code = "PARSE ERROR"


class APIError(AppError):
    code = "API ERROR"


class NetworkError(AppError):
    code = "NETWORK ERROR"


class RequestTimeout(AppError):
    code = "TIMEOUT"
