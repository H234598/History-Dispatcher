# Sicherheitsinvarianten

Diese Invarianten sind die nicht verhandelbare Baseline für alle folgenden Implementierungsschnitte.

| ID | Invariante | Aktuelle Durchsetzung | Automatischer Nachweis |
|---|---|---|---|
| `SI-001` | Die Control-API ist ausschließlich lokal über einen Unix-Socket erreichbar; es gibt keinen IP-Listener. | `socketserver.UnixStreamServer` und systemd-`RestrictAddressFamilies` | `test_control_service_is_local_unix_socket_with_peer_credentials`, `test_systemd_units_keep_local_only_hardening_baseline` |
| `SI-002` | Nur derselbe lokale Benutzer darf Control-Requests senden. | `SO_PEERCRED`, Vergleich mit `os.getuid()`, Socketmodus `0600` | `test_control_service_is_local_unix_socket_with_peer_credentials` |
| `SI-003` | History-Payloads werden mit AES-256-GCM und einem dedizierten Secret-Service-Schlüssel geschützt. | `AESGCM`, 32-Byte-Key, AAD-gebundene Verschlüsselung | `test_payload_crypto_is_aes_gcm_with_secret_service_and_no_plaintext_fallback` sowie bestehende Kryptotests |
| `SI-004` | Ein fehlender oder ungültiger Schlüssel führt niemals zu Klartextfallback. | `KeyUnavailable`; keine alternative Plaintextspeicherung | Kryptotest und Quellvertragstest |
| `SI-005` | Der Desktopstatus ist atomar, owner-only, payloadfrei und auf 64 KiB begrenzt. | Tempfile, `fsync`, `chmod 0600`, `os.replace`, Writerlimit | `test_status_snapshot_is_private_atomic_and_hard_bounded` |
| `SI-006` | Das Cinnamon-Applet greift weder direkt auf SQLite noch auf Telegram, HTTP oder Vault zu. | Snapshotreader und fester CLI-Einstieg | `test_applet_is_snapshot_only_shell_free_and_uses_fixed_action_entrypoint` |
| `SI-007` | Applet-Subprozesse werden nicht über Shellstrings gestartet; erlaubte Aktionen sind explizit allowlistet. | direkte argv, `ALLOWED_ACTIONS`, CLI-`applet-action` | Appletvertragstest und bestehende Applet-Statiktests |
| `SI-008` | Destruktive Backendaktionen benötigen Vorschau, kurzlebiges Token und exakten Bestätigungstext. | `admin.preview`/`admin.execute`, 30-Sekunden-Token, Store-Revision | bestehender `test_preview_execute_requires_exact_confirmation` |
| `SI-009` | Dienst und Collector laufen mit gehärteten systemd-User-Units. | `NoNewPrivileges`, `ProtectSystem`, `ProtectHome`, `RestrictNamespaces`, `UMask` | systemd-Vertragstest und bestehende Unit-Tests |
| `SI-010` | Appletfehler oder -entfernung stoppen weder Dienst, Collector noch Queue. | Removal-Hook räumt nur lokale Cancellables, Timer und Menü auf | `test_applet_removal_only_cleans_local_resources` und isolierter Cinnamon-Lauf |

## Änderungsregel

Eine Änderung, die eine Invariante aufweicht, benötigt:

1. einen eigenen ADR mit Sicherheitsbegründung;
2. explizite Nutzerfreigabe;
3. aktualisierte Negativ- und Fehler-Injektionstests;
4. einen dokumentierten Rollbackpfad.

Fehlt einer dieser Nachweise, ist die Änderung nicht mergefähig.
