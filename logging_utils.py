"""Rotating UTF-8 diagnostics without credentials or third-party wire logging."""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class SafeFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")
        self.secrets = tuple(value for value in secrets if value)

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)(Bearer\s+)\S+", r"\1[REDACTED]", text)


def configure_logging(directory: Path, *, debug: bool, api_key: str = "") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    for old in root.handlers[:]:
        root.removeHandler(old)
        old.close()
    formatter = SafeFormatter((api_key,))
    handler = RotatingFileHandler(
        directory / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)
    for name in ("httpx", "httpcore", "urllib3", "PIL"):
        logging.getLogger(name).setLevel(logging.WARNING)
