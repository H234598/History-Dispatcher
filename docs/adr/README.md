# Architecture Decision Records

| ADR | Entscheidung |
|---|---|
| [ADR-001](ADR-001-routing-source-of-truth.md) | Backendkonfiguration ist alleinige Routingquelle. |
| [ADR-002](ADR-002-local-database-semantics.md) | DB-Schalter steuern ein optionales verschlüsseltes Langzeitarchiv, nicht die Betriebsqueue. |
| [ADR-003](ADR-003-stable-history-types.md) | Ereignisorientierte, versionierte History-Typen. |
| [ADR-004](ADR-004-classification-authority.md) | Gestufte Klassifikationsautorität mit fail-closed Legacyfallback. |
| [ADR-005](ADR-005-router-worker-topology.md) | Zentraler Route-Plan, zielgebundene Worker. |
| [ADR-006](ADR-006-delivery-data-model.md) | Event-, Route-, Ziel-, Empfänger- und Attempt-Ebenen. |
| [ADR-007](ADR-007-telegram-ownership.md) | TeeBotus bleibt Telegram-Auslieferer. |
| [ADR-008](ADR-008-telegram-project-filter.md) | Exakter stabiler Project-ID-Filter. |
| [ADR-009](ADR-009-vault-destination.md) | Sichere lokale Obsidian-Inbox statt direktem Vault-/Cloudwrite. |
| [ADR-010](ADR-010-config-change-effect.md) | Regeln wirken standardmäßig nur auf neue Route-Pläne. |
| [ADR-011](ADR-011-config-apply-ux.md) | Validate → Preview/Diff → Apply mit Revision. |
| [ADR-012](ADR-012-desktop-control-ownership.md) | Dediziertes Applet schreibt, TeeBotus spiegelt read-only. |
| [ADR-013](ADR-013-status-contract-compatibility.md) | Status v2 mit zeitlich begrenztem v1-Dualwriter. |
| [ADR-014](ADR-014-notification-deduplication.md) | Backendsequenz plus opaque lokale Dedupe-Metadaten. |
| [ADR-015](ADR-015-safe-mode-and-poll-owner.md) | Safe Mode übernehmen; Backend bleibt alleiniger Poll-/Workerowner. |
| [ADR-016](ADR-016-parity-strategy.md) | Auditierte lokale Adaption statt gemeinsamer Runtimebibliothek. |
