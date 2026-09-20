from __future__ import annotations

import pytest

from models import ParseError
from parser import parse_question


@pytest.mark.parametrize("pattern", ["{}.", "{}、", "{}:", "{}：", "({})", "（{}）"])
def test_supported_punctuation(pattern: str) -> None:
    text = "以下关于 Python 的说法正确的是：\n" + "\n".join(
        f"{pattern.format(label)} {value}"
        for label, value in zip(
            "ABCD", ["静态类型", "解释型语言", "只运行在 Windows", "不支持对象"]
        )
    )
    parsed = parse_question(text)
    assert parsed.question == "以下关于 Python 的说法正确的是："
    assert list(parsed.choices) == list("ABCD")
    assert parsed.choices["B"] == "解释型语言"


@pytest.mark.parametrize("count", [2, 4, 5, 10])
def test_dynamic_option_count(count: int) -> None:
    text = "Choose the correct answer.\n" + "\n".join(
        f"{chr(65 + index)}. Choice {index + 1}" for index in range(count)
    )
    assert len(parse_question(text).choices) == count


def test_continuations_preserve_line_breaks_and_code_spacing() -> None:
    result = parse_question(
        "代码输出是什么？\n请考虑中文和 English。\n"
        "A. 第一行\n第二行，仍属于 A\n"
        "B. x  =  1\nprint(x)\n"
        "C. 第三项"
    )
    assert result.question == "代码输出是什么？\n请考虑中文和 English。"
    assert result.choices == {
        "A": "第一行\n第二行，仍属于 A",
        "B": "x  =  1\nprint(x)",
        "C": "第三项",
    }


@pytest.mark.parametrize("count", [2, 4, 5, 10])
def test_bare_labels_with_text(count: int) -> None:
    text = "Select one.\n" + "\n".join(
        f"{chr(65 + index)} Choice {index}" for index in range(count)
    )
    result = parse_question(text)
    assert len(result.choices) == count
    assert result.choices["A"] == "Choice 0"


def test_bare_labels_on_their_own_lines() -> None:
    result = parse_question(
        "哪个正确？\nA\n第一项\n续行\nB\n第二项\nC\n第三项\nD\n第四项"
    )
    assert result.choices["A"] == "第一项\n续行"
    assert result.choices["D"] == "第四项"


def test_ocr_spaces_fullwidth_and_mixed_markers() -> None:
    result = parse_question(
        "\ufeff  哪个正确？  \r\n\r\n"
        "  Ａ  ．  首项  \r\n  （ B ） 次项\r\n"
        "\tC  ：\t第三项\r\n  D、  末项\r\n"
    )
    assert result.question == "哪个正确？"
    assert result.choices == {"A": "首项", "B": "次项", "C": "第三项", "D": "末项"}


def test_inline_options() -> None:
    result = parse_question(
        "Which function prints?\nA. scanf B. printf C. malloc D. fopen"
    )
    assert result.choices == {"A": "scanf", "B": "printf", "C": "malloc", "D": "fopen"}


def test_question_and_options_on_same_line() -> None:
    result = parse_question("哪个正确？A：甲 B：乙 C：丙")
    assert result.question == "哪个正确？"
    assert result.choices == {"A": "甲", "B": "乙", "C": "丙"}


def test_inline_and_multiline_options_together() -> None:
    result = parse_question(
        "Pick one.\nA. first B. second\ncontinued\nC. third D. last"
    )
    assert result.choices["B"] == "second\ncontinued"
    assert result.choices["D"] == "last"


def test_compact_ocr_options() -> None:
    result = parse_question("哪项正确？\nA.Python 是解释型\nB.Java 是脚本")
    assert result.choices["A"] == "Python 是解释型"


def test_english_article_in_stem_not_an_option() -> None:
    result = parse_question(
        "A car travels at constant speed.\nWhat is true?\nA. It accelerates\nB. It does not"
    )
    assert result.question.startswith("A car travels")
    assert result.choices["B"] == "It does not"


def test_embedded_letters_and_attributes_not_split() -> None:
    result = parse_question(
        "What does A mean?\n"
        "A. print(A) and object.A and A.method()\n"
        "B. A variable named A is allowed\n"
        "C. Choices (A) and (B) are both wrong"
    )
    assert result.choices["A"] == "print(A) and object.A and A.method()"
    assert result.choices["C"] == "Choices (A) and (B) are both wrong"


def test_does_not_normalize_question_or_answer_symbols() -> None:
    result = parse_question("x＝１，哪项正确？\nA. y＝２\nB. x == 1")
    assert result.question == "x＝１，哪项正确？"
    assert result.choices["A"] == "y＝２"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n",
        "Question without choices.",
        "A. first\nB. second",  # no question
        "Question\nA. first",  # only one choice
        "Question\nA\nB\nC\nD",  # labels without contents
        "Question\nA B C D",  # letters sharing a line are not choices
        "Question\nA\nB\nC\nD\nE",
        "Question\nA.\nB. second",  # empty first choice
        "Question\nA. first\nB.",  # empty last choice
        "Question\nA. first\nC. third",  # missing B
        "Question\nB. second\nC. third",  # missing A
        "Question\nA. first\nA. duplicate\nB. second",
        "Question\nA first\nA duplicate\nB second",
        "Question A. first A. duplicate B. second",
        "Question\nA. first A. duplicate\nB. second",
        "Question\nA. first\nB. second\nB. duplicate",
        "Question\nA. first\nC. third\nB. second",
        "Question\nA. first\nB. refers to (C) in a formula",  # two plausible layouts
        "Question\nA. first\nB. call C.method()",  # could be a compact third option
        "Question\n" + "\n".join(f"{chr(65 + n)}. item {n}" for n in range(11)),
    ],
)
def test_rejects_incomplete_and_ambiguous_lists(text: str) -> None:
    with pytest.raises(ParseError):
        parse_question(text)
