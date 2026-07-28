# Telegram-Transportmodi

**Vertragsversion:** `telegram-provider/v1`  
**Stand:** 28. Juli 2026

## 1. Zweck

Der History-Dispatcher unterstützt zwei gleichwertige, explizit auswählbare
Telegram-Provider:

| Provider | Transportprozess | Credential-Eigentümer | Routenauflösung |
|---|---|---|---|
| `teebotus` | TeeBotus Telegramworker | TeeBotus Credential-/AccountStore | private TeeBotus Admin-/Accountrouten |
| `history_dispatcher` | eigener History-Dispatcher Telegramworker | Secret Service / owner-only Credentialprovider des History-Dispatchers | opaque native Recipientprofile |

Der zentrale History-Dispatcher bleibt in beiden Modi Eigentümer von Event,
Route-Plan, Targetdelivery, Recipientdelivery, Attempt, Lease und Aggregation.

## 2. Unveränderliche Providerbindung

Jeder Telegram-Route-Plan enthält ein `telegram_transport`-Fragment:

```json
{
  "schema_version": 1,
  "provider": "teebotus",
  "bridge_capability": "history-dispatcher-telegram-v2"
}
```

oder:

```json
{
  "schema_version": 1,
  "provider": "history_dispatcher",
  "credential_ref": "telegram_primary",
  "recipient_refs": ["status_admin_primary"]
}
```

Alle Werte außer dem Provider sind opaque Referenzen. Token, Chat-ID und
Message-Ref im Klartext sind kein zulässiger Vertragswert.

Der Provider ist Teil des Planhashes. Ein Worker muss beim Claim seine Provider-
Capability melden. Ein Missmatch wird abgelehnt. Es gibt keinen automatischen
Fallback von TeeBotus zum nativen Worker oder umgekehrt.

## 3. Einstellungsfeld

Der spätere Backend-Routingeditor erhält das Feld:

| Feld | Widget | Default | Backendpfad | Wirkung |
|---|---|---|---|---|
| `telegram-dispatch-provider` | Combobox/Radio | `teebotus` | `routing.telegram.provider` | nur neue Route-Pläne; vorhandene Pläne unverändert |

Sichtbare Optionen:

- **Über TeeBotus ausliefern**
- **Direkt über History-Dispatcher ausliefern**

Das Feld wird staged über `config.get_redacted` → `validate` → `preview` →
`apply` mit `expected_revision` geändert. Es wird nicht als dconf-Key
persistiert. Die UI zeigt beim Providerwechsel, dass offene Altpläne nicht
automatisch umgeschaltet werden.

Für den nativen Modus kommen im selben Custom-Widget hinzu:

- opaque Credentialprofil;
- verwaltete Recipientprofile;
- Credentialstatus `nicht eingerichtet`, `gültig`, `fehlerhaft`;
- write-only Aktion zum Setzen oder Ersetzen des Tokens;
- Testaktion gegen einen explizit ausgewählten Recipient, mit Vorschau und
  Bestätigung.

Der Tokenwert wird nach dem Schreiben niemals wieder in die UI zurückgegeben.

## 4. Gemeinsam übernommene TeeBotus-Semantik

Die native Implementierung adaptiert aus TeeBotus:

1. vor einem Claim muss mindestens eine aktuell routbare private Route
   existieren;
2. `accepted`, `delivered`, `acknowledged` sind monotone Erfolgsränge;
3. bereits erfolgreiche Empfänger werden bei Retry ausgeschlossen;
4. veraltete, nicht mehr routbare Fehlerempfänger können terminal `skipped`
   werden, ohne neue Erfolge global zurückzustufen;
5. partielle Ergebnisse werden je Empfänger persistiert;
6. unklarer Crash nach externem Accept wird `possible_duplicate`, nicht blind
   erneut gesendet;
7. Ausgabe wird vor Transport redigiert, escaped, begrenzt und deterministisch
   segmentiert;
8. Telegram `retry_after` hat Vorrang vor exponentiellem Backoff mit Jitter;
9. Completion-/Callbackfehler bleiben atomar spool- beziehungsweise
   reconciliationfähig;
10. kein Worker claimt fremde Targets oder einen anderen Provider.

## 5. Native Credentialgrenze

Der native Worker erhält keine Secrets aus TOML, dconf, Route-Plänen oder dem
Status-Snapshot. Vorgesehen sind getrennte Secret-Service-Attribute, zum
Beispiel:

```text
application=history-dispatcher
purpose=telegram-bot-token
profile=telegram_primary
```

Die Konfiguration speichert nur `credential_ref = "telegram_primary"`.
Recipientprofile lösen intern opaque Namen auf Chat-IDs auf; rohe Chat-IDs
werden nicht im Applet, Snapshot oder Plan angezeigt.

## 6. Kein automatischer Fallback

Folgende Abkürzungen sind verboten:

- bei TeeBotus-Ausfall automatisch nativ senden;
- bei nativem Fehler automatisch an TeeBotus übergeben;
- denselben Targetclaim gleichzeitig beiden Workern anbieten;
- Providerwechsel durch simples Neustarten eines Workers;
- erfolgreiche Empfänger durch Replan zurücksetzen.

Der sichere Operatorweg lautet: Ursache prüfen, Delivery reconciliieren,
`routes.replan_preview`, exakte Auswahl bestätigen und erst danach einen neuen
Plan erzeugen.

## 7. Implementierungsreihenfolge

1. Provider-Typen, Route-Plan-Fragment, Planhash und monotone Recipient-Merge-
   Semantik;
2. target-/provider-spezifische Store-Claims und Worker-Capability;
3. Config-v2-Feld und revisionsgesicherte Settings-UI;
4. TeeBotus-v2-Adapter gegen den gemeinsamen Contract;
5. nativer Credentialprovider und Bot-API-Client;
6. Formatter, Batching, Rate-Limit und Reconciliation;
7. systemd-Härtung und Status v2;
8. beide Provider im identischen Fehler-Injektionskorpus;
9. kontrollierter Canary ohne automatischen Fallback.
