# Produktive Config-v2-API

**Schnitt:** `PR-HD-Config-v2-Writer` / PR #12  
**Stand:** 31. Juli 2026  
**Status:** implementiert; finale Merge-Gates laufen

## 1. Ziel und Sicherheitsgrenze

Config v2 ist die einzige Backend-Quelle der Wahrheit für die Telegram-
Providerwahl und deren opaque Profilreferenzen. Cinnamon/dconf speichert weder
Routingregeln noch Credentials oder Chat-IDs.

Dieser Schnitt persistiert ausdrücklich **keinen Bot-Token**. Er implementiert:

- strikte produktive Routingkonfiguration;
- Revisionen und kanonische Patches;
- Validate, Preview und Compare-and-Swap-Apply;
- atomaren TOML-Write, Reload-Verifikation und Rollback;
- bounded `config_audit`;
- additive Same-User-Socketoperationen;
- vollständige Kompatibilität der bisherigen Config-v1-Operationen.

Write-only Secret-Service-Tokenoperationen folgen in einem separaten PR.

## 2. Produktives TOML-Schema

```toml
[routing.telegram]
provider = "teebotus"
credential_ref = ""
recipient_refs = []
```

Erlaubte Provider:

```text
teebotus
history_dispatcher
```

`credential_ref` und `recipient_refs` sind ausschließlich opaque Profilnamen.
Sie dürfen keine Tokens, numerischen Chat-IDs, Pfade oder Steuerzeichen
enthalten. Es werden höchstens 32 Recipientprofile akzeptiert; Duplikate werden
in stabiler Reihenfolge entfernt.

Im Modus `teebotus` müssen native Credential- und Recipientprofile leer sein.
Im Modus `history_dispatcher` referenzieren sie ausschließlich spätere
Secret-Service- beziehungsweise Recipientprofil-Einträge.

## 3. Same-User-Socketoperationen

Additive Operationen im Control-Protokoll v1:

```text
config.get_redacted
config.validate_patch
config.preview_apply
config.apply
```

Die bestehenden Operationen bleiben unverändert verfügbar:

```text
config.get
config.validate
config.apply mit values
```

### 3.1 `config.get_redacted`

Read-only; keine Request-ID erforderlich.

Antwort:

```json
{
  "schema_version": 2,
  "config_revision": "sha256",
  "routing": {
    "telegram": {
      "provider": "teebotus",
      "credential_ref": "",
      "recipient_refs": []
    }
  }
}
```

### 3.2 `config.validate_patch`

Erfordert eine Request-ID und akzeptiert exakt:

```json
{
  "patch": {
    "routing": {
      "telegram": {
        "provider": "history_dispatcher",
        "credential_ref": "telegram_primary",
        "recipient_refs": ["status_admin_primary"]
      }
    }
  }
}
```

Die Antwort enthält ausschließlich die kanonisch normalisierte Patchstruktur.
Die Operation ist dauerhaft request-idempotent.

### 3.3 `config.preview_apply`

Erfordert eine Request-ID und akzeptiert exakt:

```json
{
  "expected_revision": "sha256",
  "patch": {
    "routing": {
      "telegram": {
        "provider": "history_dispatcher",
        "credential_ref": "telegram_primary",
        "recipient_refs": ["status_admin_primary"]
      }
    }
  }
}
```

Antwort:

```json
{
  "schema_version": 2,
  "expected_revision": "sha256",
  "fingerprint": "sha256",
  "confirmation": "APPLY 0123456789ab",
  "effect": "new_route_plans_only",
  "changes": {},
  "preview_token": "one-use-token",
  "expires_in_seconds": 60
}
```

Der Previewtoken:

- wird nur einmal ausgegeben;
- wird intern ausschließlich als SHA-256 gehalten;
- läuft nach 60 Sekunden ab;
- ist an Revision, Patch und Fingerprint gebunden;
- wird nicht in TOML, Status, Snapshot oder Idempotenzantwort gespeichert;
- lässt einen identischen Request-ID-Replay fail-closed als
  `idempotency_in_progress` stehen.

### 3.4 Previewgestütztes `config.apply`

Erfordert eine Request-ID und exakt:

```json
{
  "expected_revision": "sha256",
  "preview_token": "one-use-token",
  "fingerprint": "sha256",
  "confirmation": "APPLY 0123456789ab"
}
```

Der Applypfad:

1. verbraucht den Previewtoken vor jeder Mutation;
2. prüft Ablauf, Revision, Fingerprint und exakte Bestätigung;
3. lädt die aktuelle Datei erneut und führt Compare-and-Swap aus;
4. schreibt über den bestehenden privaten atomaren TOML-Writer;
5. lädt die Datei erneut und verifiziert die erwartete neue Revision;
6. schreibt einen bounded Auditdatensatz;
7. aktualisiert Service und ConfigManager auf denselben Reload-Stand;
8. veröffentlicht den neuen Provider im redigierten Status-v2-Snapshot.

Ein erfolgreicher Apply ist dauerhaft request-idempotent. Derselbe Body mit
derselben Request-ID liefert die gespeicherte Antwort. Derselbe verbrauchte
Previewtoken unter einer anderen Request-ID wird abgewiesen.

## 4. Audit und Rollback

Jeder erfolgreiche oder fachlich abgewiesene Config-v2-Apply schreibt, sofern
das additive Schema vorhanden ist, ausschließlich:

- HMAC-pseudonymisierten `actor_key`;
- Operation `config.apply_v2`;
- Revision vorher/nachher;
- SHA-256 des Previewtokens;
- Ergebnis und Reason-Code;
- Anzahl geänderter Leaf-Felder;
- UTC-Zeitstempel.

Patchwerte, Recipientprofile und Previewtoken werden nicht in `config_audit`
geschrieben.

Fehler beim TOML-Write, Post-Write-Reload oder finalen Audit führen zum
vollständigen Dateirückbau und Reload des vorherigen Configstands. Der
Settingspfad führt keine Datenbankmigration durch; ohne vorhandene
`config_audit`-Tabelle ist produktiver Apply fail-closed.

## 5. Rückwärtskompatibilität

Unverändert:

- `config.get` liefert den bisherigen öffentlichen Gesamtstatus;
- `config.validate` validiert weiterhin eine explizite Configdatei;
- `config.apply` mit flachem `values`-Objekt verwendet weiterhin die bestehende
  Safe-Values-Allowlist;
- vorhandene Request-ID-Idempotenz bleibt erhalten.

Ein Legacy-Apply synchronisiert einen bereits lazy erzeugten Config-v2-Manager
auf den neuen aktuellen Configstand.

## 6. Leak- und Größengrenzen

- Patch: höchstens 64 KiB endliches JSON;
- Previewregistry: höchstens 128 aktive Einträge;
- Request-ID: bestehende 128-Zeichen-/Steuerzeichen-Grenze;
- keine Bot-Tokens oder rohen Chat-IDs in Config, API, Audit oder Snapshot;
- Provideränderungen wirken ausschließlich auf neu erzeugte Route-Pläne;
- keine automatische Neuplanung oder Cross-Provider-Fallbacks.

## 7. Nächster Schnitt

Der nächste separat reviewbare Schnitt ergänzt:

1. native Credentialprofile im Secret Service;
2. write-only Setzen/Ersetzen/Löschen des Bot-Tokens;
3. Credentialstatus ohne Secretwert;
4. bestätigten Credentialtest;
5. Leaktests für API, Audit, Logs, TOML, Snapshot und dconf.

Erst danach wird der native Telegram-Bot-API-Worker aktiviert.
