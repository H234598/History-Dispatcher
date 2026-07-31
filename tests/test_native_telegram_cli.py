from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from history_dispatcher import cli
from history_dispatcher.config import default_config


@dataclass
class FakeStopEvent:
    set_calls: int = 0

    def set(self) -> None:
        self.set_calls += 1

    def is_set(self) -> bool:
        return False


class FakeWorker:
    instances: list["FakeWorker"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.run_calls: list[object] = []
        self.__class__.instances.append(self)

    def run_forever(self, stop_event: object) -> None:
        self.run_calls.append(stop_event)


def test_cli_constructs_native_worker_from_internal_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = default_config(tmp_path / "config.toml")
    key_provider = object()
    delivery_store = object()
    provider_api = object()
    secret_store = object()
    client = object()
    stop_event = FakeStopEvent()
    signal_handlers: dict[int, object] = {}

    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "SecretServiceKeyProvider", lambda: key_provider)
    monkeypatch.setattr(
        cli,
        "DeliveryStore",
        lambda database_path, provider: (
            delivery_store
            if database_path == config.database_path and provider is key_provider
            else pytest.fail("unexpected DeliveryStore arguments")
        ),
    )
    monkeypatch.setattr(
        cli,
        "ProviderApiV2",
        lambda store: provider_api
        if store is delivery_store
        else pytest.fail("unexpected ProviderApiV2 store"),
    )
    monkeypatch.setattr(
        cli,
        "NativeTelegramSecretStore",
        lambda: secret_store,
    )
    monkeypatch.setattr(cli, "TelegramBotApiClient", lambda: client)
    monkeypatch.setattr(cli, "NativeTelegramWorker", FakeWorker)
    monkeypatch.setattr(cli.threading, "Event", lambda: stop_event)
    monkeypatch.setattr(
        cli.signal,
        "signal",
        lambda number, handler: signal_handlers.__setitem__(number, handler),
    )

    result = cli.main(["--config", str(config.config_path), "telegram-worker"])

    assert result == 0
    assert len(FakeWorker.instances) == 1
    worker = FakeWorker.instances[-1]
    assert worker.kwargs["provider_api"] is provider_api
    assert worker.kwargs["secret_store"] is secret_store
    assert worker.kwargs["client"] is client
    assert worker.kwargs["key_provider"] is key_provider
    assert worker.kwargs["worker_id"] == "native_telegram_worker"
    assert worker.run_calls == [stop_event]
    assert signal_handlers
    next(iter(signal_handlers.values()))(15, None)
    assert stop_event.set_calls == 1


def test_cli_returns_bounded_redacted_error_on_worker_initialization_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = default_config(tmp_path / "config.toml")
    marker = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
    monkeypatch.setattr(cli, "load_config", lambda _path: config)

    def fail_key_provider():
        raise RuntimeError(f"private {marker}")

    monkeypatch.setattr(cli, "SecretServiceKeyProvider", fail_key_provider)

    result = cli.main(["--config", str(config.config_path), "telegram-worker"])

    captured = capsys.readouterr()
    assert result == 1
    assert marker not in captured.out
    assert marker not in captured.err
    assert len(captured.err) <= 600
    assert "native Telegram worker unavailable" in captured.err
