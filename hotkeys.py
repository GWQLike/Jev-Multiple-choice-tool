"""Exact key chords with repeat suppression (no OS listener created on import)."""

from __future__ import annotations

from collections.abc import Hashable

from models import ConfigError


def canonical_key(key: object) -> Hashable:
    name = getattr(key, "name", None)
    if name:
        for modifier in ("alt", "ctrl", "shift", "cmd"):
            if name in (modifier, modifier + "_l", modifier + "_r"):
                return modifier
        return name
    char = getattr(key, "char", None)
    if char is not None:
        return str(char).lower()
    vk = getattr(key, "vk", None)
    # pynput represents left/right modifier aliases as virtual-key objects in
    # HotKey.parse; collapse them so <alt>+<alt_l> is rejected as a duplicate.
    if vk in (160, 161):
        return "shift"
    if vk in (162, 163):
        return "ctrl"
    if vk in (164, 165):
        return "alt"
    if vk in (91, 92):
        return "cmd"
    return ("vk", vk)


def parse_hotkey(value: str) -> frozenset[Hashable]:
    from pynput.keyboard import HotKey

    try:
        keys = HotKey.parse(value)
        normalized = frozenset(canonical_key(key) for key in keys)
        if not keys or len(keys) != len(normalized):
            raise ValueError("Empty or duplicate chord")
        return normalized
    except (ValueError, KeyError, TypeError) as exc:
        raise ConfigError("Invalid hotkey; use pynput syntax such as <alt>+q.") from exc


class HotkeyState:
    def __init__(
        self, answer: frozenset[Hashable], exit_keys: frozenset[Hashable]
    ) -> None:
        self.answer = answer
        self.exit_keys = exit_keys
        self.pressed: set[Hashable] = set()

    def press(self, key: Hashable) -> str | None:
        if key in self.pressed:
            return None
        self.pressed.add(key)
        if self.pressed == self.exit_keys:
            return "exit"
        if self.pressed == self.answer:
            return "answer"
        return None

    def release(self, key: Hashable) -> None:
        self.pressed.discard(key)
