import pytest

from models import OCRError, OCRLine
from ocr_engine import arrange_lines


def line(text, x, y):
    return OCRLine(text, ((x, y), (x + 50, y), (x + 50, y + 20), (x, y + 20)), 0.99)


def test_row_order_and_fragments():
    result = arrange_lines(
        [
            line("world", 90, 11),
            line("B. second", 10, 70),
            line("Hello", 10, 10),
            line("A. first", 10, 40),
        ]
    )
    assert result.text == "Hello world\nA. first\nB. second"
    assert len(result.lines) == 3


def test_empty():
    with pytest.raises(OCRError):
        arrange_lines([])
