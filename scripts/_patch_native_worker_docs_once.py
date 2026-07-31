from __future__ import annotations

from pathlib import Path


README = Path("README.md")
ADDENDUM = Path("docs/implementation-plan-addendum-telegram.md")
CONTROL = Path("docs/contracts/control-protocol-v1.md")
PLAN = Path("docs/superpowers/plans/2026-07-31-native-telegram-worker.md")
PROGRESS = Path("docs/implementation-progress.md")


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    readme = README.read_text(encoding="utf-8")
    readme = replace_once(
        readme,
        "- [`docs/native-telegram-credentials.md`](docs/native-telegram-credentials.md)\n  — explicit schema-v4 migration and write-only Secret-Service boundary;",
        "- [`docs/native-telegram-credentials.md`](docs/native-telegram-credentials.md)\n  — explicit schema-v4 migration and write-only Secret-Service boundary;\n- [`docs/native-telegram-worker.md`](docs/native-telegram-worker.md)\n  — fixed-host Bot API client, formatter, provider-v2 worker and hardened unit;",
        label="readme runbook link",
    )
    readme = replace_once(
        readme,
        "This boundary intentionally performs no Telegram network request. `getMe`, test\nmessages and the Bot API worker belong to the next separately reviewed slice.",
        "The credential API itself performs no Telegram network request. The separately\nreviewed native worker consumes its internal lookup methods immediately before each\nsend and never exposes a public credential-read operation.\n\n## Native Telegram worker\n\nThe native worker is fixed to `https://api.telegram.org:443`, uses the standard\nverified TLS context, and internally allowlists only `getMe`, `sendMessage`, and\n`sendDocument`. There is no configurable URL, proxy, redirect, HTTP fallback,\nlocal Bot API server, rich formatting, inbound update path or TeeBotus fallback.\n\nShort payloads are sent as one plain-text message. Longer payloads use exactly\none bounded UTF-8 text document rather than a multi-request segment sequence.\nThis preserves recipient-level atomicity after crashes.\n\nRun interactively:\n\n```bash\npython -m history_dispatcher \\\n  --config ~/.config/history-dispatcher/config.toml \\\n  telegram-worker\n```\n\nThe dedicated systemd unit is rendered but not enabled by default. Explicit\nactivation requires:\n\n```bash\npython -m history_dispatcher.systemd \\\n  --python /path/to/.venv-py313/bin/python \\\n  --config ~/.config/history-dispatcher/config.toml \\\n  --enable \\\n  --enable-telegram-worker\n```\n\nOnly that unit receives `AF_INET/AF_INET6`; the main service and collector remain\nrestricted to local Unix/file sockets. See\n[`docs/native-telegram-worker.md`](docs/native-telegram-worker.md).",
        label="readme worker section",
    )
    readme = replace_once(
        readme,
        "The TeeBotus provider is already integrated against this contract. The native\nHistory-Dispatcher worker may now use the internal credential lookup boundary,\nbut the Bot API client, formatting, rate-limit handling and systemd worker remain\nthe next slice.",
        "The TeeBotus provider and the native History-Dispatcher worker both use this\ncontract. The native worker resolves opaque Secret-Service profiles per recipient,\nrenews claims before network access, records recipient outcomes immediately, maps\nTelegram `retry_after` into the shared backoff contract, and preserves uncertain\npost-connect outcomes as monotone `possible_duplicate`. Live canaries remain a\nseparate explicit gate.",
        label="readme provider status",
    )
    README.write_text(readme, encoding="utf-8")

    addendum = ADDENDUM.read_text(encoding="utf-8")
    addendum = replace_once(
        addendum,
        "- [ ] **PR-HD-Native-Telegram** – nativer Telegramworker mit Bot-API, Formatter,\n  Batching, Rate-Limit und Reconciliation.",
        "- [ ] **PR-HD-15 / PR-HD-Native-Telegram** – nativer Telegramworker mit\n  fixed-host Bot API, Formatter, Provider-v2-Lifecycle, Rate-Limit und\n  Reconciliation; funktional grün, finale Gates und Merge offen.",
        label="addendum pr15",
    )
    replacements = (
        ("- [ ] `TG-E-001` nativer Bot-API-Client.", "- [x] `TG-E-001` nativer fixed-host Bot-API-Client mit TLS-, Timeout- und Größenlimits."),
        ("- [ ] `TG-E-002` Formatter, Segmentierung und Attachmentfallback.", "- [x] `TG-E-002` deterministischer Plain-Text-Formatter und atomarer Ein-Dokument-Fallback."),
        ("- [ ] `TG-E-003` Telegram-`retry_after` im echten nativen Adapter; Store-Backoff,\n  Jitter und Max Attempts sind vorhanden.", "- [x] `TG-E-003` Telegram-`retry_after` im nativen Adapter an den gemeinsamen Store-Backoff übergeben."),
        ("- [ ] `TG-E-006` nativer systemd-Worker und Heartbeatloop.", "- [x] `TG-E-006` nativer CLI-/systemd-Worker und redigierter Heartbeatloop; Aktivierung explizit opt-in."),
        ("- [ ] `TG-F-002b` Rate-Limit, Hänger, Oversize und vollständige\n  Recipient-Partial-Tests für beide echten Provider.", "- [x] `TG-F-002b-native` Rate-Limit, Connect-/Read-Hänger, Oversize, malformed Response und Recipient-Partial-Fälle für Native getestet.\n- [ ] `TG-F-002b-shared` erweiterten vollständigen Fault-Korpus erneut gegen TeeBotus und Native gemeinsam abnehmen."),
    )
    for old, new in replacements:
        addendum = replace_once(addendum, old, new, label=old[:40])
    addendum = replace_once(
        addendum,
        "## 10. Nächster Schnitt: nativer Telegramworker\n\nAls nächster Schnitt folgen:\n\n1. interner Bot-Token- und Chat-ID-Lookup;\n2. gehärteter Bot-API-Client mit TLS, Timeouts und bounded Antworten;\n3. deterministische Formatierung und Segmentierung;\n4. Telegram-`retry_after`, Backoff und Rate-Limit;\n5. empfängerweise Resultate und Crash-after-Accept-Reconciliation;\n6. systemd-User-Worker und Heartbeat;\n7. gemeinsamer Fault-Korpus gegen TeeBotus und Native;\n8. getrennte Canaries ohne Cross-Provider-Doppelversand.",
        "## 10. Aktiver Schnitt: nativer Telegramworker\n\nPR #15 hat funktional umgesetzt:\n\n1. internen Bot-Token- und Chat-ID-Lookup unmittelbar vor jedem Send;\n2. fixed-host Bot-API-Client mit TLS, Timeouts und bounded Antworten;\n3. deterministische Plain-Text-Formatierung mit Ein-Dokument-Fallback;\n4. Telegram-`retry_after`, Backoff und Rate-Limit;\n5. empfängerweise Resultate und Crash-after-Accept-`possible_duplicate`;\n6. explizit opt-in-fähigen systemd-User-Worker und redigierte Heartbeats;\n7. versionierten nativen Fault-Korpus.\n\nOffen bleiben Merge-Gates, getrennte Live-Canaries ohne Cross-Provider-\nDoppelversand und danach die Cinnamon-Providerauswahl.",
        label="addendum active worker",
    )
    ADDENDUM.write_text(addendum, encoding="utf-8")

    control = CONTROL.read_text(encoding="utf-8")
    control = replace_once(
        control,
        "## Provider-v2-Operationen\n\nDie Provider-v2-Operationen sind additive Same-User-Workeroperationen. Ihr\nvollständiger Body-/Responsevertrag steht in `docs/provider-api-v2.md`.",
        "## Provider-v2-Operationen\n\nDie Provider-v2-Operationen sind additive Same-User-Workeroperationen. Ihr\nvollständiger Body-/Responsevertrag steht in `docs/provider-api-v2.md`.\n\nDer native Telegramworker führt keine neue öffentliche Socketoperation ein. Er\nkonsumiert `ProviderApiV2` in-process mit der unveränderlichen Bindung\n`telegram/history_dispatcher/history-dispatcher-telegram-native-v1`. Claim,\nRenew, Recipientregistrierung, Recipientresultate, Complete und Heartbeat laufen\ndadurch über denselben validierten Vertrag wie externe Providerworker. Der\nNetzwerktransport und seine Fehlersemantik stehen in\n`docs/native-telegram-worker.md`.",
        label="control native worker",
    )
    CONTROL.write_text(control, encoding="utf-8")

    plan = PLAN.read_text(encoding="utf-8")
    for step in (1, 4, 5):
        plan = replace_once(
            plan,
            f"- [ ] **Step {step}:",
            f"- [x] **Step {step}:",
            label=f"plan task5 step {step}",
        )
    PLAN.write_text(plan, encoding="utf-8")

    progress = PROGRESS.read_text(encoding="utf-8")
    progress = replace_once(
        progress,
        "- [ ] Betreiber-Runbook, README, Telegram-Addendum und finalen PR-Vertrag aktualisieren;",
        "- [x] Betreiber-Runbook `docs/native-telegram-worker.md`, README, Telegram-Addendum und Control-Protokoll aktualisiert;",
        label="progress docs",
    )
    PROGRESS.write_text(progress, encoding="utf-8")


if __name__ == "__main__":
    main()
