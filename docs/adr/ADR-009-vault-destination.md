# ADR-009: Vault-Ziel als sichere Obsidian-Inbox

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Direktes Schreiben in eine produktive Obsidian-Vaultwurzel oder direkt zu pCloud/WebDAV vergrößert Traversal-, Konflikt-, Credential- und Sync-Risiken.

## Entscheidung

`vault` bedeutet im Pflichtumfang eine private lokale Obsidian-Inbox mit klarer Importergrenze. Ein eigener Worker schreibt atomare, idempotente Markdowndateien. Direkter produktiver Vault- oder Cloudwrite bleibt eine spätere ADR.

## Konsequenzen

- Keine Vaultcredentials oder Netzwerkclients im Applet.
- Dateinamen und Pfade basieren auf bounded Slug plus opaque ID, nie auf untrusted Text allein.
- Fremde Kollisionen werden quarantänisiert, nicht überschrieben.

## Verifikation

Vaulttests müssen Traversal, Symlinks, Crash vor Replace, Readonly, Diskfull, Hashkonflikt und Resume abdecken.
