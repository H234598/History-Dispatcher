# ADR-011: Apply-UX für Backendkonfiguration

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Livewrites pro Feld oder Tastendruck erzeugen Teilzustände und Lost-Update-Risiken, besonders bei mehrzeiligen Projektlisten.

## Entscheidung

Backendwerte folgen dem Ablauf `Laden → Bearbeiten → Validate → Preview/Diff → Apply`. Apply bindet ein kurzlebiges Token an kanonischen Diff und `expected_revision`. UI-Präferenzen dürfen weiterhin unmittelbar in dconf gespeichert werden.

## Konsequenzen

- Der Settingseditor hält ungespeicherte Werte lokal.
- Revisionskonflikte überschreiben nichts und bieten Reload beziehungsweise Copy-changes.
- Backendwrites bleiben atomar und auditiert.

## Verifikation

Widget- und API-Tests müssen genau einen Applycall, Konflikterhalt, Token-TTL und Replayablehnung nachweisen.
