"""Validated configuration; paths are relative to the application, not the shell."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from models import CaptureRegion, ConfigError

APP_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Config:
    hotkey: str = "<alt>+q"
    exit_hotkey: str = "<alt>+<shift>+q"
    capture_mode: str = "fixed"
    capture_region: CaptureRegion = field(
        default_factory=lambda: CaptureRegion(300, 200, 1200, 700)
    )
    popup_duration_ms: int = 1500
    confidence_warning_threshold: float = 0.8
    jev_timeout_seconds: float = 5.0
    # Kept under the old field name because main.py passes this value to the
    # protocol adapter.  The value now comes exclusively from AI Gateway.
    jev_model: str = "typesafe-ai/jev"
    typesafe_api_key: str = field(default="", repr=False)
    debug: bool = False


def load_config(
    path: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> Config:
    source = path if path is not None else APP_DIR / "config.json"
    try:
        data = (
            json.loads(source.read_text(encoding="utf-8-sig"))
            if source.exists()
            else {}
        )
    except (OSError, ValueError) as exc:
        raise ConfigError(
            "Cannot read configuration JSON; check config.json encoding and syntax."
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError("Configuration must be a JSON object.")
    allowed = set(Config.__dataclass_fields__)
    if data.keys() - allowed:
        raise ConfigError("Unknown configuration fields; compare config.example.json.")
    defaults = Config()
    values = {name: data.get(name, getattr(defaults, name)) for name in allowed}
    region = values["capture_region"]
    if isinstance(region, dict):
        if set(region) != {"left", "top", "width", "height"}:
            raise ConfigError("capture_region needs left, top, width and height.")
        if any(type(v) is not int for v in region.values()):
            raise ConfigError("Capture coordinates must be integer physical pixels.")
        region = CaptureRegion(**region)
    if not isinstance(region, CaptureRegion) or region.width <= 0 or region.height <= 0:
        raise ConfigError("Capture width and height must be positive.")
    values["capture_region"] = region
    if values["capture_mode"] not in ("fixed", "select"):
        raise ConfigError("capture_mode must be fixed or select.")
    for name in ("hotkey", "exit_hotkey", "jev_model", "typesafe_api_key"):
        if not isinstance(values[name], str):
            raise ConfigError(f"{name} must be a string.")
        values[name] = values[name].strip()
    if not values["jev_model"]:
        raise ConfigError("jev_model must not be empty.")
    # Older config.example.json files used jev-latest.  Normalize that legacy
    # value so a copied local config still routes to the required Gateway
    # model.  Other model names are rejected rather than silently changing the
    # provider contract.
    if values["jev_model"] == "jev-latest":
        values["jev_model"] = "typesafe-ai/jev"
    if values["jev_model"] != "typesafe-ai/jev":
        raise ConfigError("jev_model must be typesafe-ai/jev.")
    from hotkeys import parse_hotkey

    if parse_hotkey(values["hotkey"]) == parse_hotkey(values["exit_hotkey"]):
        raise ConfigError("Answer and exit hotkeys must differ.")
    duration = values["popup_duration_ms"]
    if type(duration) is not int or not 100 <= duration <= 60000:
        raise ConfigError("popup_duration_ms must be an integer between 100 and 60000.")
    for name, minimum, maximum in (
        ("confidence_warning_threshold", 0, 1),
        ("jev_timeout_seconds", 0.1, 120),
    ):
        value = values[name]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not minimum <= value <= maximum
        ):
            raise ConfigError(
                f"{name} must be a finite number between {minimum} and {maximum}."
            )
    if type(values["debug"]) is not bool:
        raise ConfigError("debug must be a JSON boolean.")
    env = os.environ if environ is None else environ
    # Keep the dataclass field for main.py compatibility, but never read a
    # credential from config.json.  This prevents accidental key commits and
    # makes the new environment variable the single source of truth.
    values["typesafe_api_key"] = env.get("AI_GATEWAY_API_KEY", "").strip()
    return Config(**values)
