import json

import pytest

from config import Config, load_config
from hotkeys import HotkeyState
from models import ConfigError


def write_config(tmp_path, value, encoding="utf-8"):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding=encoding)
    return path


def test_defaults_and_missing_file(tmp_path):
    assert load_config(tmp_path / "absent.json", environ={}) == Config()


def test_bom_and_key_precedence(tmp_path):
    path = write_config(
        tmp_path,
        {"typesafe_api_key": "config-secret", "jev_model": "jev-latest"},
        "utf-8-sig",
    )
    config = load_config(path, environ={"AI_GATEWAY_API_KEY": " env-secret "})
    assert config.typesafe_api_key == "env-secret"
    assert config.jev_model == "typesafe-ai/jev"
    assert "secret" not in repr(config)
    assert (
        load_config(path, environ={"AI_GATEWAY_API_KEY": " "}).typesafe_api_key
        == ""
    )


def test_legacy_key_environment_is_ignored(tmp_path):
    path = write_config(tmp_path, {"typesafe_api_key": "config-secret"})
    config = load_config(
        path,
        environ={"TYPESAFE_API_KEY": "old-secret", "AI_GATEWAY_API_KEY": ""},
    )
    assert config.typesafe_api_key == ""


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"debug": "false"},
        {"capture_mode": "unknown"},
        {"hotkey": ""},
        {"hotkey": "<alt>+<alt_l>+q"},
        {"exit_hotkey": "<alt>+q"},
        {"popup_duration_ms": True},
        {"popup_duration_ms": -1},
        {"jev_timeout_seconds": 0},
        {"confidence_warning_threshold": float("nan")},
        {"confidence_warning_threshold": 1.1},
        {"jev_model": "other-model"},
        {"capture_region": {"left": 0, "top": 0, "width": 0, "height": 1}},
        {"capture_region": {"left": False, "top": 0, "width": 1, "height": 1}},
        {"capture_region": {}},
        {"typesafe_api_key": 12},
        {"typo": 1},
    ],
)
def test_invalid(tmp_path, value):
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, value), environ={})


def test_negative_monitor_coordinates(tmp_path):
    config = load_config(
        write_config(
            tmp_path,
            {
                "capture_region": {
                    "left": -1200,
                    "top": -50,
                    "width": 800,
                    "height": 400,
                }
            },
        ),
        environ={},
    )
    assert config.capture_region.left == -1200


def test_chords_ignore_repeat_and_exit_does_not_answer():
    state = HotkeyState(frozenset({"alt", "q"}), frozenset({"alt", "shift", "q"}))
    assert state.press("alt") is None
    assert state.press("shift") is None
    assert state.press("q") == "exit"
    assert state.press("q") is None
    state.release("shift")
    assert state.press("q") is None
    state.release("q")
    assert state.press("q") == "answer"
