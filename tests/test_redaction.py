from __future__ import annotations

import pytest

from history_dispatcher.redaction import contains_sensitive_marker, redact_text


@pytest.mark.parametrize(
    "raw, forbidden",
    [
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("Authorization=Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        (
            'WWW-Authenticate: Digest realm="private", nonce="secret-value"',
            "secret-value",
        ),
        ("password = 'secret value with spaces'", "secret value with spaces"),
        ('token="abc def ghi"', "abc def ghi"),
    ],
)
def test_redaction_consumes_complete_headers_and_quoted_secret_values(
    raw: str,
    forbidden: str,
) -> None:
    redacted = redact_text(raw)

    assert forbidden not in redacted
    assert "[redacted]" in redacted
    assert contains_sensitive_marker(redacted) is False


@pytest.mark.parametrize(
    "raw",
    [
        "Authorization: Bearer abcdefghijklmnop",
        "password=supersecret",
        "https://user:password@example.invalid/path",
    ],
)
def test_sensitive_marker_guard_covers_every_redaction_family(raw: str) -> None:
    assert contains_sensitive_marker(raw) is True
