from models import Answer, CaptureRegion


def test_answer_confidence_is_independent_of_winning_probability():
    answer = Answer("B", 0.81, {"A": 0.12, "B": 0.88})
    assert answer.confidence != answer.probabilities[answer.answer]


def test_capture_region_allows_negative_virtual_desktop_coordinates():
    region = CaptureRegion(-1920, -50, 1200, 700)
    assert region.as_dict()["left"] == -1920
