from __future__ import annotations

import hashlib

import pytest

from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.identifiers import persistent_opaque_id


def test_persistent_identifier_is_stable_keyed_and_namespace_separated() -> None:
    first_key = StaticKeyProvider(b"k" * 32)
    second_key = StaticKeyProvider(b"z" * 32)

    first = persistent_opaque_id(first_key, "project", "/home/alice/repository")
    repeated = persistent_opaque_id(first_key, "project", "/home/alice/repository")
    different_namespace = persistent_opaque_id(
        first_key,
        "session",
        "/home/alice/repository",
    )
    different_key = persistent_opaque_id(
        second_key,
        "project",
        "/home/alice/repository",
    )

    assert first == repeated
    assert first.startswith("project_")
    assert first != different_namespace
    assert first != different_key
    assert "/home/alice" not in first
    assert hashlib.sha256(b"/home/alice/repository").hexdigest()[:32] not in first


def test_persistent_identifier_normalizes_unicode_and_bounds_length() -> None:
    provider = StaticKeyProvider(b"k" * 32)

    composed = persistent_opaque_id(provider, "project", "Caf\u00e9", length=20)
    decomposed = persistent_opaque_id(provider, "project", "Cafe\u0301", length=20)

    assert composed == decomposed
    assert len(composed.removeprefix("project_")) == 20
    assert persistent_opaque_id(provider, "project", "") == "project_unknown"


def test_persistent_identifier_rejects_unbounded_namespaces() -> None:
    provider = StaticKeyProvider(b"k" * 32)

    with pytest.raises(ValueError, match="namespace"):
        persistent_opaque_id(provider, "../project", "value")
    with pytest.raises(ValueError, match="prefix"):
        persistent_opaque_id(provider, "project", "value", prefix="bad/prefix")
