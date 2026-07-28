# Security

History-Dispatcher is local-only by design. Payloads are encrypted with an
AES-256-GCM key retrieved from the user Secret Service; there is no plaintext
fallback. The control endpoint is an owner-only Unix socket and all applet
reads are bounded to the versioned status snapshot.

The normative, test-linked baseline is maintained in
[`docs/contracts/security-invariants.md`](docs/contracts/security-invariants.md).
Any architecture, protocol, systemd, crypto, service, applet, classifier,
fixture, or other implementation change that weakens one of those invariants
requires an ADR, explicit negative tests and a documented rollback path.

## Rollout and fixture privacy

Raw Codex/agent rollout JSONL files may contain prompts, answers, paths,
repository metadata, identities and credentials. They must never be committed,
attached to a public issue or included in a support bundle.

Only fixtures produced or independently verified under the contract in
[`docs/history-classification.md`](docs/history-classification.md) may enter
`tests/fixtures/codex/`. The sanitizer uses deterministic pseudonyms, replaces
free text and unknown strings, writes atomically and creates a hash-only
manifest. A sanitized fixture still requires human review and the automated
leak/manifest tests before merge.

Please report security issues privately to the repository owner rather than
opening a public issue with exploit details. Include the affected commit,
reproduction steps, and whether the issue involves payload confidentiality,
queue integrity, classification leakage, or Cinnamon process safety.
