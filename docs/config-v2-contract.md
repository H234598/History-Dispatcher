# Config-v2 Contract

## Zweck

Dieser Schnitt friert den Konfigurationsvertrag für den späteren Settings- und
Credentialpfad ein.

Noch keine produktive Credentialoperation findet hier statt.

## Telegram Provider

```toml
[routing.telegram]
provider = "teebotus"
```

Erlaubte Werte:

- `teebotus`
- `history_dispatcher`

## Sicherheitsgrenzen

- kein Bot-Token in TOML;
- keine Chat-ID in dconf;
- keine Credentials in Statussnapshots;
- keine Provideränderung bestehender Route-Pläne ohne expliziten Revisionsprozess;
- keine automatische Providerumschaltung.

## Apply-Prozess

Der geplante Ablauf:

1. aktuelle Revision lesen;
2. Änderung validieren;
3. Preview erzeugen;
4. Previewtoken bestätigen;
5. atomisch anwenden;
6. Config-Audit schreiben.

## Implementierungsgrenze

Die echte Config-Loader-Integration und Secret-Service-Verwaltung folgen in den
nächsten Commits dieses PR-Schnitts.
