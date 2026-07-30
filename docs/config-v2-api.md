# Config v2 API contract

**Schnitt:** PR-HD-06-config-v2-api
**Status:** vorbereitet

## Ziel

Config v2 trennt dauerhaft zwischen:

- Backend-Routing- und Worker-Konfiguration (Source of Truth);
- lokalen Cinnamon-UI-Präferenzen.

Das Cinnamon-Applet darf keine Routingregeln, Credentials oder Providerentscheidungen dauerhaft in dconf speichern.

## Providerumschaltung

Telegram erhält den stabilen Backendwert:

```toml
[routing.telegram]
provider = "teebotus"
```

Erlaubte Werte:

```text
teebotus
history_dispatcher
```

Der Wert wirkt ausschließlich auf neue Route-Pläne.

## API-Ablauf

```text
config.get_redacted
        |
        v
config.validate_patch
        |
        v
config.preview_apply
        |
        v
config.apply
```

Jeder Apply benötigt:

- erwartete Config-Revision;
- kurzlebiges Preview-Token;
- identischen Diff-Fingerprint;
- explizite Bestätigung.

## Sicherheitsgrenzen

Nicht erlaubt:

- Bot-Tokens in TOML;
- Chat-IDs in dconf;
- Credentials im Snapshot;
- freie Commands aus Settings;
- automatische Provider-Fallbacks.

Erlaubt:

- opaque Credentialprofile;
- Secret-Service-Referenzen;
- redigierte Statusinformationen.

## Nachfolgende Umsetzung

Die Implementierung erfolgt in:

- `history_dispatcher/config.py`
- `history_dispatcher/service.py`
- `history_dispatcher/cli.py`
- `history_dispatcher/protocol.py`
- `tests/test_config_v2.py`
- `tests/test_config_api.py`

## Abnahme

Erst abgeschlossen bei:

- Config-Revisionen getestet;
- Conflict-Verhalten getestet;
- Token-Replay abgewiesen;
- atomarer Write nachgewiesen;
- keine Secrets in Diagnose/Snapshot/Config sichtbar.
