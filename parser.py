"""Conservative, layout-aware parsing of one OCR'd single-choice question.

Only option markers are normalized. In particular, NFKC is deliberately not
applied to question text: that would change full-width symbols in code/math.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from models import ParseError, Question

# Small token patterns recognize markers; sequence/context checks below decide
# whether a token actually belongs to an option list.
_EXPLICIT = re.compile(
    r"(?:[(（][ \t\u3000]*(?P<wrapped>[A-ZＡ-Ｚ])[ \t\u3000]*[)）]"
    r"|(?P<plain>[A-ZＡ-Ｚ])[ \t\u3000]*(?P<mark>[.．、:：]))"
)
_BARE = re.compile(r"[ \t\u3000]*(?P<label>[A-ZＡ-Ｚ])(?=$|[ \t\u3000])")
_INLINE_BOUNDARIES = frozenset(";；,，?？!！:：")


@dataclass(frozen=True)
class _Marker:
    label: str
    start: int
    end: int
    line_start: bool
    explicit: bool
    wrapped: bool = False
    compact_dot: bool = False

    @property
    def strength(self) -> int:
        if not self.explicit:
            return 1
        return 3 if self.line_start else 2


def _letter(value: str) -> str:
    return chr(ord(value) - 0xFEE0) if "Ａ" <= value <= "Ｚ" else value


def _markers(text: str) -> list[_Marker]:
    found: list[_Marker] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\n")
        first = len(body) - len(body.lstrip())
        for match in _EXPLICIT.finditer(body):
            start, end = match.span()
            anchored = start == first
            if not anchored and (
                start == 0
                or not (
                    body[start - 1].isspace() or body[start - 1] in _INLINE_BOUNDARIES
                )
            ):
                continue
            found.append(
                _Marker(
                    label=_letter(match.group("wrapped") or match.group("plain")),
                    start=offset + start,
                    end=offset + end,
                    line_start=anchored,
                    explicit=True,
                    wrapped=bool(match.group("wrapped")),
                    compact_dot=(
                        match.group("mark") in {".", "．"}
                        and end < len(body)
                        and not body[end].isspace()
                    ),
                )
            )
        bare = _BARE.match(body)
        # "A . content" is explicit, even though it also matches bare "A ".
        if bare is not None and not any(
            marker.start == offset + first for marker in found
        ):
            found.append(
                _Marker(
                    label=_letter(bare.group("label")),
                    start=offset + bare.start("label"),
                    end=offset + bare.end("label"),
                    line_start=True,
                    explicit=False,
                )
            )
        offset += len(line)
    return sorted(found, key=lambda marker: marker.start)


def _block(text: str) -> str:
    # Keep internal spacing, punctuation and line breaks for code and formulas.
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _build(text: str, markers: list[_Marker]) -> Question | None:
    if not 2 <= len(markers) <= 10:
        return None
    if [marker.label for marker in markers] != [
        chr(ord("A") + index) for index in range(len(markers))
    ]:
        return None
    question = _block(text[: markers[0].start])
    if not question:
        return None
    choices: dict[str, str] = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start if index + 1 < len(markers) else len(text)
        content = _block(text[marker.end : end])
        if not content:
            return None
        choices[marker.label] = content
    return Question(question=question, choices=choices)


def parse_question(text: str) -> Question:
    """Parse 2–10 nonempty, consecutively labelled A–J options.

    Explicit markers may share a line. Bare letters need a line boundary and
    whitespace (or their own line). Strong line boundaries can disambiguate
    inline parenthesized references or compact attribute expressions. Otherwise
    malformed or ambiguous option lists fail instead of silently losing text.
    """
    if not isinstance(text, str) or not text.strip():
        raise ParseError("OCR text is empty.")
    source = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    candidates = _markers(source)
    starts = [index for index, marker in enumerate(candidates) if marker.label == "A"]
    results: list[Question] = []
    for index in starts:
        start = candidates[index]
        # A natural-language bare "A car ..." in the stem must not prevent a
        # subsequent explicit option list. Repeated equally strong A's do.
        if any(
            previous.label == "A" and previous.strength >= start.strength
            for previous in candidates[:index]
        ):
            continue
        suffix = candidates[index:]
        complete = _build(source, suffix)
        if complete is not None:
            results.append(complete)

        anchored = [marker for marker in suffix if marker.line_start]
        omitted = [marker for marker in suffix if not marker.line_start]
        # Referencing "(A)" or "A.method" inside an answer is common. A second
        # spaced "A. ..." is a competing option boundary and must not be hidden.
        if (
            start.line_start
            and omitted
            and all(marker.wrapped or marker.compact_dot for marker in omitted)
        ):
            line_result = _build(source, anchored)
            if line_result is not None:
                results.append(line_result)

    if len(results) != 1:
        raise ParseError(
            "Expected one question followed by 2–10 nonempty consecutive options A–J."
        )
    return results[0]
