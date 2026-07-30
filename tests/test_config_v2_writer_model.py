from __future__ import annotations

from pathlib import Path

import pytest

from history_dispatcher.config import load_config, write_config
from history_dispatcher.telegram_provider import TelegramDispatchProvider


def test_routing_telegram_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            (
                "[routing.telegram]",
                'provider = "history_dispatcher"',
                'credential_ref = "telegram_primary"',
                'recipient_refs = ["status_admin_primary", "ops_admin"]',
                "",
            )
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert (
        config.telegram_provider
        is TelegramDispatchProvider.HISTORY_DISPATCHER
    )
    assert config.telegram_credential_ref == "telegram_primary"
    assert config.telegram_recipient_refs == (
        "status_admin_primary",
        "ops_admin",
    )

    write_config(config)
    reloaded = load_config(path)

    assert reloaded == config
    rendered = path.read_text(encoding="utf-8")
    assert "[routing.telegram]" in rendered
    assert 'provider = "history_dispatcher"' in rendered
    assert 'credential_ref = "telegram_primary"' in rendered
    assert (
        'recipient_refs = ["status_admin_primary", "ops_admin"]'
        in rendered
    )


def test_routing_telegram_defaults_to_teebotus(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")

    config = load_config(path)

    assert config.telegram_provider is TelegramDispatchProvider.TEEBOTUS
    assert config.telegram_credential_ref == ""
    assert config.telegram_recipient_refs == ()


@pytest.mark.parametrize(
    "toml",
    (
        '[routing.telegram]\nprovider = "automatic"\n',
        '[routing.telegram]\nbot_token = "secret"\n',
        '[routing.telegram]\nchat_id = "-1001234567890"\n',
        (
            '[routing.telegram]\nprovider = "history_dispatcher"\n'
            'recipient_refs = ["-1001234567890"]\n'
        ),
        (
            '[routing.telegram]\nprovider = "history_dispatcher"\n'
            'credential_ref = "../token"\n'
        ),
        (
            '[routing.telegram]\nprovider = "teebotus"\n'
            'credential_ref = "telegram_primary"\n'
        ),
        (
            '[routing.telegram]\nprovider = "teebotus"\n'
            'recipient_refs = ["status_admin_primary"]\n'
        ),
    ),
)
def test_routing_telegram_rejects_unsafe_values(
    tmp_path: Path,
    toml: str,
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(toml, encoding="utf-8")

    with pytest.raises(ValueError):
        load_config(path)


def test_routing_telegram_deduplicates_opaque_recipient_refs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            (
                "[routing.telegram]",
                'provider = "history_dispatcher"',
                'credential_ref = "telegram_primary"',
                (
                    'recipient_refs = ["status_admin_primary", '
                    '"status_admin_primary", "ops_admin"]'
                ),
                "",
            )
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.telegram_recipient_refs == (
        "status_admin_primary",
        "ops_admin",
    )


def test_routing_telegram_limits_recipient_profiles(tmp_path: Path) -> None:
    refs = ", ".join(f'"recipient_{index}"' for index in range(33))
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            (
                "[routing.telegram]",
                'provider = "history_dispatcher"',
                'credential_ref = "telegram_primary"',
                f"recipient_refs = [{refs}]",
                "",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="recipient"):
        load_config(path)
