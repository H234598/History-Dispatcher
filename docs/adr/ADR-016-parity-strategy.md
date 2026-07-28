# ADR-016: Coding-Paritätsstrategie

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

SOC, TeeBotus und codex-usage besitzen wertvolle Appletmuster. Eine gemeinsame Runtimeabhängigkeit würde jedoch Offlineinstallation, Cinnamon-Modulauflösung und Fehlerdomänen koppeln.

## Entscheidung

Helfer werden lokal und auditiert adaptiert beziehungsweise bei ungeklärter Lizenz funktional neu implementiert. Eine Markdown- und YAML-Paritätsmatrix sowie Verhaltenstests halten die Semantik synchron. Es gibt keine gemeinsame Applet-Runtimebibliothek.

## Konsequenzen

- Bewusste Duplikation benötigt Reuse Ledger, Quellcommit und Test-IDs.
- Referenzänderungen erfolgen in getrennten Follow-up-PRs.
- Nicht passende Features werden als N/A oder bewusst abweichend dokumentiert.

## Verifikation

Das spätere Parity-Gate prüft eindeutige Capability-IDs, vier Repositoryzustände, Lizenzstatus, Zielpfad und vorhandene Paritätstests.
