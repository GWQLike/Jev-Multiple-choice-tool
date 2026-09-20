"""Provider adapter tests use HTTPX's in-memory transport, never the live API."""

from __future__ import annotations

import json
import logging
import math
import traceback
from typing import Any

import httpx
import pytest

from jev_client import JevClient
from models import APIError, NetworkError, Question, RequestTimeout


@pytest.fixture
def question() -> Question:
    return Question("哪个函数用于格式化输出？", {"A": "scanf", "B": "printf"})


def valid_response() -> dict[str, Any]:
    return {
        "model": "typesafe-ai/jev",
        "answers": {
            "answer": {
                "type": "choice",
                "choice": "B",
                "confidence": 0.81,
                "probabilities": {"A": 0.12, "B": 0.88},
            }
        },
        "usage": {"input_tokens": 42, "output_tokens": 12},
    }


def response_transport(payload: Any) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=payload))


def test_official_request_shape_and_reuse(question: Question) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=valid_response())

    with JevClient("test-key", transport=httpx.MockTransport(handle)) as client:
        underlying = client._client
        first = client.answer(question)
        second = client.answer(question)
        assert client._client is underlying
        assert not underlying.is_closed
    assert underlying.is_closed
    assert first == second
    assert first.answer == "B"
    assert first.confidence == 0.81
    assert first.probabilities["B"] == 0.88
    assert len(requests) == 2
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.headers["Content-Type"] == "application/json"
    body = json.loads(request.content)
    assert set(body) == {"model", "state", "questions"}
    assert body["model"] == "typesafe-ai/jev"
    assert body["state"] == {"question": question.question}
    assert set(body["questions"]) == {"answer"}
    choice = body["questions"]["answer"]
    assert set(choice) == {"type", "instructions", "criteria"}
    assert choice["type"] == "choice"
    assert isinstance(choice["instructions"], str)
    assert choice["criteria"] == question.choices
    assert request.extensions["timeout"]["read"] == 5.0


@pytest.mark.parametrize("count", range(2, 11))
def test_dynamic_option_counts(count: int) -> None:
    choices = {chr(65 + index): f"Option {index}" for index in range(count)}
    selected = list(choices)[-1]

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "typesafe-ai/jev"
        assert body["questions"]["answer"]["criteria"] == choices
        return httpx.Response(
            200,
            json={
                "answers": {
                    "answer": {
                        "type": "choice",
                        "choice": selected,
                        "confidence": 1,
                        "probabilities": {key: int(key == selected) for key in choices},
                    }
                }
            },
        )

    with JevClient("test-key", transport=httpx.MockTransport(handle)) as client:
        result = client.answer(Question("Pick the last option.", choices))
    assert result.answer == selected
    assert set(result.probabilities) == set(choices)


def test_gateway_environment_key_and_model_are_sent(
    monkeypatch: pytest.MonkeyPatch, question: Question
) -> None:
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gateway-env-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "legacy-key")
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=valid_response())

    with JevClient(None, transport=httpx.MockTransport(handle)) as client:
        client.answer(question)

    assert len(requests) == 1
    request = requests[0]
    assert request.headers["Authorization"] == "Bearer gateway-env-key"
    body = json.loads(request.content)
    assert body["model"] == "typesafe-ai/jev"


def test_non_gateway_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="typesafe-ai/jev"):
        JevClient("test-key", model="jev-latest")


@pytest.mark.parametrize("key", ["", "   ", "bad\nkey", "中文"])
def test_missing_or_invalid_key_never_makes_request(
    key: str, question: Question
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        pytest.fail("An invalid key must not cause a request")

    with JevClient(key, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(APIError, match="API key"):
            client.answer(question)


@pytest.mark.parametrize("status", [301, 307, 400, 401, 403, 404, 422, 429, 500, 529])
def test_http_errors_and_redirects_do_not_retry(
    status: int, question: Question
) -> None:
    requests = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            status,
            json={"detail": "secret-provider-body"},
            headers={"Location": "https://example.org", "Retry-After": "1"},
        )

    with JevClient("test-key", transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(APIError, match=f"HTTP {status}") as caught:
            client.answer(question)
    assert requests == 1
    assert "secret-provider-body" not in str(caught.value)


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (httpx.ConnectTimeout, RequestTimeout),
        (httpx.ReadTimeout, RequestTimeout),
        (httpx.WriteTimeout, RequestTimeout),
        (httpx.PoolTimeout, RequestTimeout),
        (httpx.ConnectError, NetworkError),
        (httpx.ReadError, NetworkError),
        (httpx.RemoteProtocolError, NetworkError),
    ],
)
def test_transport_errors_are_safe(
    raised: type[httpx.RequestError],
    expected: type[Exception],
    question: Question,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise raised("sensitive-provider-message", request=request)

    with JevClient("test-key", transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(expected) as caught:
            client.answer(question)
    formatted = "".join(traceback.format_exception(caught.value))
    assert "sensitive-provider-message" not in formatted + caplog.text
    assert "test-key" not in formatted + caplog.text
    assert calls == 1


@pytest.mark.parametrize("content", [b"not json", b"", b'{"secret":', b"\xff"])
def test_invalid_json(content: bytes, question: Question) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=content)
    )
    with JevClient("test-key", transport=transport) as client:
        with pytest.raises(APIError, match="invalid Choice response"):
            client.answer(question)


@pytest.mark.parametrize(
    "payload", [None, [], "answer", {}, {"answers": []}, {"answers": {}}]
)
def test_missing_answer_structure(payload: Any, question: Question) -> None:
    with JevClient("test-key", transport=response_transport(payload)) as client:
        with pytest.raises(APIError):
            client.answer(question)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type", "noul"),
        ("type", None),
        ("choice", "C"),
        ("choice", ["B"]),
        ("choice", None),
        ("confidence", None),
        ("confidence", "0.81"),
        ("confidence", True),
        ("confidence", False),
        ("confidence", -0.1),
        ("confidence", 1.1),
        ("probabilities", None),
        ("probabilities", []),
        ("probabilities", {"A": 0.12}),
        ("probabilities", {"A": 0.12, "B": 0.88, "C": 0.0}),
        ("probabilities", {"A": 0.2, "B": 0.3}),
        ("probabilities", {"A": 0.9, "B": 0.1}),
        ("probabilities", {"A": -0.1, "B": 1.1}),
        ("probabilities", {"A": False, "B": True}),
        ("probabilities", {"A": "0.12", "B": 0.88}),
    ],
)
def test_invalid_fields(field: str, value: Any, question: Question) -> None:
    payload = valid_response()
    payload["answers"]["answer"][field] = value
    with JevClient("test-key", transport=response_transport(payload)) as client:
        with pytest.raises(APIError):
            client.answer(question)


@pytest.mark.parametrize("field", ["type", "choice", "confidence", "probabilities"])
def test_missing_required_choice_field(field: str, question: Question) -> None:
    payload = valid_response()
    del payload["answers"]["answer"][field]
    with JevClient("test-key", transport=response_transport(payload)) as client:
        with pytest.raises(APIError):
            client.answer(question)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("field", ["confidence", "probabilities"])
def test_nonfinite_values(value: float, field: str, question: Question) -> None:
    payload = valid_response()
    payload["answers"]["answer"][field] = (
        value if field == "confidence" else {"A": value, "B": 0.88}
    )
    # Raw content deliberately exercises nonstandard JSON numbers accepted by
    # Python's JSON decoder but forbidden by the adapter's numeric checks.
    content = json.dumps(payload).encode()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=content)
    )
    with JevClient("test-key", transport=transport) as client:
        with pytest.raises(APIError):
            client.answer(question)


def test_probability_rounding_is_allowed_without_changing_confidence(
    question: Question,
) -> None:
    payload = valid_response()
    payload["answers"]["answer"]["probabilities"] = {"A": 0.12, "B": 0.8795}
    with JevClient("test-key", transport=response_transport(payload)) as client:
        result = client.answer(question)
    assert result.confidence == 0.81
    assert result.probabilities == {"A": 0.12, "B": 0.8795}


@pytest.mark.parametrize(
    "request_id", ["req-123_abc", "evil\nforged-line", "test-key", "x" * 129]
)
def test_logs_do_not_expose_secrets_or_untrusted_bodies(
    request_id: str,
    question: Question,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            401,
            content=b"secret-provider-body",
            headers={"x-typesafe-request-id": request_id},
        )
    )
    with caplog.at_level(logging.DEBUG, logger="jev_client"):
        with JevClient("test-key", transport=transport) as client:
            with pytest.raises(APIError):
                client.answer(question)
    assert "test-key" not in caplog.text
    assert "secret-provider-body" not in caplog.text
    assert "forged-line" not in caplog.text
    assert "status=401" in caplog.text
    assert ("request_id=req-123_abc" in caplog.text) == (request_id == "req-123_abc")


def test_timeout_override(question: Question) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert set(request.extensions["timeout"].values()) == {1.25}
        return httpx.Response(200, json=valid_response())

    with JevClient("test-key", 1.25, transport=httpx.MockTransport(handle)) as client:
        client.answer(question)


@pytest.mark.parametrize("timeout", [0, -1, math.nan, math.inf, True, "5"])
def test_invalid_timeout(timeout: Any) -> None:
    with pytest.raises(ValueError):
        JevClient("test-key", timeout)


def test_closed_client(question: Question) -> None:
    client = JevClient("test-key", transport=response_transport(valid_response()))
    client.close()
    client.close()
    with pytest.raises(APIError, match="closed"):
        client.answer(question)


@pytest.mark.parametrize(
    "bad_question",
    [
        Question("", {"A": "a", "B": "b"}),
        Question("Q", {"A": "a"}),
        Question("Q", {str(index): "option" for index in range(11)}),
        Question("Q", {"A": " ", "B": "b"}),
        Question("Q", {"": "a", "B": "b"}),
    ],
)
def test_invalid_question_is_rejected_before_network(bad_question: Question) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        pytest.fail("An invalid question must not cause a request")

    with JevClient("test-key", transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(APIError):
            client.answer(bad_question)
