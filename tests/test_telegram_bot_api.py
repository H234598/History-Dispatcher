from __future__ import annotations

import json
import socket
import ssl
from dataclasses import dataclass, field

import pytest

from history_dispatcher.telegram_bot_api import (
    MAX_MULTIPART_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    TELEGRAM_API_HOST,
    TELEGRAM_API_PORT,
    TELEGRAM_API_TIMEOUT_SECONDS,
    TelegramApiPossibleDuplicate,
    TelegramApiRateLimited,
    TelegramApiRejected,
    TelegramApiSuccess,
    TelegramBotApiClient,
)


TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
CHAT_ID = "-1001234567890"


@dataclass
class FakeResponse:
    status: int
    body: bytes
    read_error: Exception | None = None
    read_sizes: list[int] = field(default_factory=list)

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self.read_error is not None:
            raise self.read_error
        if size < 0:
            return self.body
        return self.body[:size]


class FakeConnection:
    def __init__(
        self,
        response: FakeResponse,
        *,
        connect_error: Exception | None = None,
        request_error: Exception | None = None,
        response_error: Exception | None = None,
    ) -> None:
        self.response = response
        self.connect_error = connect_error
        self.request_error = request_error
        self.response_error = response_error
        self.connected = False
        self.closed = False
        self.requests: list[tuple[str, str, bytes, dict[str, str]]] = []

    def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    def request(
        self,
        method: str,
        path: str,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        assert self.connected is True
        self.requests.append((method, path, body, dict(headers)))
        if self.request_error is not None:
            raise self.request_error

    def getresponse(self) -> FakeResponse:
        if self.response_error is not None:
            raise self.response_error
        return self.response

    def close(self) -> None:
        self.closed = True


class RecordingFactory:
    def __init__(self, connections: list[FakeConnection]) -> None:
        self.connections = list(connections)
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        host: str,
        port: int,
        *,
        timeout: int,
        context: ssl.SSLContext,
    ) -> FakeConnection:
        self.calls.append(
            {
                "host": host,
                "port": port,
                "timeout": timeout,
                "context": context,
            }
        )
        return self.connections.pop(0)


def _response(status: int, payload: object) -> FakeResponse:
    return FakeResponse(
        status=status,
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )


def _client(connection: FakeConnection) -> tuple[TelegramBotApiClient, RecordingFactory]:
    factory = RecordingFactory([connection])
    return (
        TelegramBotApiClient(
            connection_factory=factory,
            boundary_factory=lambda: "historydispatcherboundary",
        ),
        factory,
    )


def test_send_message_uses_fixed_verified_https_connection() -> None:
    connection = FakeConnection(
        _response(200, {"ok": True, "result": {"message_id": 42}})
    )
    client, factory = _client(connection)

    result = client.send_message(TOKEN, CHAT_ID, "hello")

    assert result == TelegramApiSuccess(message_id=42)
    assert factory.calls[0]["host"] == TELEGRAM_API_HOST == "api.telegram.org"
    assert factory.calls[0]["port"] == TELEGRAM_API_PORT == 443
    assert factory.calls[0]["timeout"] == TELEGRAM_API_TIMEOUT_SECONDS == 10
    context = factory.calls[0]["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert connection.connected is True
    assert connection.closed is True

    method, path, body, headers = connection.requests[0]
    assert method == "POST"
    assert path == f"/bot{TOKEN}/sendMessage"
    assert headers["Content-Type"] == "application/json"
    assert headers["Connection"] == "close"
    assert headers["Content-Length"] == str(len(body))
    assert json.loads(body) == {"chat_id": CHAT_ID, "text": "hello"}
    assert "parse_mode" not in body.decode("utf-8")


def test_get_me_is_allowlisted_and_requires_no_parameters() -> None:
    connection = FakeConnection(
        _response(200, {"ok": True, "result": {"id": 5, "is_bot": True}})
    )
    client, _factory = _client(connection)

    result = client.get_me(TOKEN)

    assert result == TelegramApiSuccess(message_id=5)
    method, path, body, _headers = connection.requests[0]
    assert method == "POST"
    assert path == f"/bot{TOKEN}/getMe"
    assert json.loads(body) == {}


def test_rate_limit_uses_bounded_retry_after() -> None:
    connection = FakeConnection(
        _response(
            429,
            {
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 17},
            },
        )
    )
    client, _factory = _client(connection)

    assert client.send_message(TOKEN, CHAT_ID, "hello") == TelegramApiRateLimited(
        retry_after_seconds=17
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (400, TelegramApiRejected("telegram_bad_request", retryable=False)),
        (401, TelegramApiRejected("telegram_unauthorized", retryable=False)),
        (403, TelegramApiRejected("telegram_forbidden", retryable=False)),
        (500, TelegramApiRejected("telegram_transient", retryable=True)),
        (302, TelegramApiRejected("telegram_redirect_forbidden", retryable=False)),
    ),
)
def test_explicit_http_errors_map_to_bounded_outcomes(
    status: int,
    expected: TelegramApiRejected,
) -> None:
    connection = FakeConnection(
        _response(
            status,
            {
                "ok": False,
                "error_code": status,
                "description": f"private {TOKEN} {CHAT_ID}",
            },
        )
    )
    client, _factory = _client(connection)

    result = client.send_message(TOKEN, CHAT_ID, "hello")

    assert result == expected
    rendered = repr(result)
    assert TOKEN not in rendered
    assert CHAT_ID not in rendered
    assert "private" not in rendered


def test_connect_failure_is_retryable_and_never_sends() -> None:
    connection = FakeConnection(
        _response(200, {"ok": True, "result": {"message_id": 1}}),
        connect_error=socket.timeout("private timeout"),
    )
    client, _factory = _client(connection)

    result = client.send_message(TOKEN, CHAT_ID, "hello")

    assert result == TelegramApiRejected("telegram_connect_failed", retryable=True)
    assert connection.requests == []
    assert connection.closed is True


@pytest.mark.parametrize(
    "phase",
    ["request", "response", "read"],
)
def test_failures_after_connect_are_possible_duplicate(phase: str) -> None:
    kwargs: dict[str, Exception] = {}
    response = _response(200, {"ok": True, "result": {"message_id": 1}})
    if phase == "request":
        kwargs["request_error"] = ConnectionResetError("private request")
    elif phase == "response":
        kwargs["response_error"] = ConnectionResetError("private response")
    else:
        response.read_error = socket.timeout("private read")
    connection = FakeConnection(response, **kwargs)
    client, _factory = _client(connection)

    result = client.send_message(TOKEN, CHAT_ID, "hello")

    assert result == TelegramApiPossibleDuplicate("telegram_accept_unknown")
    assert TOKEN not in repr(result)
    assert CHAT_ID not in repr(result)


def test_malformed_or_oversized_success_is_possible_duplicate() -> None:
    malformed = FakeConnection(FakeResponse(status=200, body=b"not-json"))
    oversized = FakeConnection(
        FakeResponse(status=200, body=b"x" * (MAX_RESPONSE_BYTES + 1))
    )
    factory = RecordingFactory([malformed, oversized])
    client = TelegramBotApiClient(
        connection_factory=factory,
        boundary_factory=lambda: "historydispatcherboundary",
    )

    assert client.send_message(TOKEN, CHAT_ID, "one") == TelegramApiPossibleDuplicate(
        "telegram_protocol_unknown"
    )
    assert client.send_message(TOKEN, CHAT_ID, "two") == TelegramApiPossibleDuplicate(
        "telegram_response_too_large"
    )
    assert malformed.response.read_sizes == [MAX_RESPONSE_BYTES + 1]
    assert oversized.response.read_sizes == [MAX_RESPONSE_BYTES + 1]


def test_malformed_explicit_error_is_retryable_protocol_error() -> None:
    connection = FakeConnection(FakeResponse(status=500, body=b"not-json"))
    client, _factory = _client(connection)

    assert client.send_message(TOKEN, CHAT_ID, "hello") == TelegramApiRejected(
        "telegram_protocol_error",
        retryable=True,
    )


@pytest.mark.parametrize("retry_after", [0, -1, "x", None])
def test_invalid_retry_after_does_not_create_unbounded_sleep(retry_after: object) -> None:
    connection = FakeConnection(
        _response(
            429,
            {
                "ok": False,
                "error_code": 429,
                "parameters": {"retry_after": retry_after},
            },
        )
    )
    client, _factory = _client(connection)

    assert client.send_message(TOKEN, CHAT_ID, "hello") == TelegramApiRejected(
        "telegram_rate_limited",
        retryable=True,
    )


def test_retry_after_is_capped_to_seven_days() -> None:
    connection = FakeConnection(
        _response(
            429,
            {
                "ok": False,
                "error_code": 429,
                "parameters": {"retry_after": 999999999},
            },
        )
    )
    client, _factory = _client(connection)

    assert client.send_message(TOKEN, CHAT_ID, "hello") == TelegramApiRateLimited(
        retry_after_seconds=604800
    )


def test_send_document_uses_one_bounded_multipart_request() -> None:
    connection = FakeConnection(
        _response(200, {"ok": True, "result": {"message_id": 77}})
    )
    client, _factory = _client(connection)

    result = client.send_document(
        TOKEN,
        CHAT_ID,
        "history-safe.txt",
        b"payload\n",
        "History export",
    )

    assert result == TelegramApiSuccess(message_id=77)
    method, path, body, headers = connection.requests[0]
    assert method == "POST"
    assert path == f"/bot{TOKEN}/sendDocument"
    assert headers["Content-Type"].startswith(
        "multipart/form-data; boundary=historydispatcherboundary"
    )
    assert len(body) < MAX_MULTIPART_REQUEST_BYTES
    assert b'name="chat_id"' in body
    assert CHAT_ID.encode("utf-8") in body
    assert b'name="document"; filename="history-safe.txt"' in body
    assert b"payload\n" in body
    assert b'name="caption"' in body


@pytest.mark.parametrize(
    ("filename", "document", "caption"),
    (
        ("../unsafe.txt", b"x", "caption"),
        ("unsafe.bin", b"x", "caption"),
        ("history-safe.txt", b"", "caption"),
        ("history-safe.txt", b"x" * MAX_MULTIPART_REQUEST_BYTES, "caption"),
        ("history-safe.txt", b"x", "x" * 901),
    ),
)
def test_send_document_rejects_unsafe_or_unbounded_input(
    filename: str,
    document: bytes,
    caption: str,
) -> None:
    connection = FakeConnection(
        _response(200, {"ok": True, "result": {"message_id": 1}})
    )
    client, _factory = _client(connection)

    with pytest.raises(ValueError):
        client.send_document(TOKEN, CHAT_ID, filename, document, caption)

    assert connection.requests == []
