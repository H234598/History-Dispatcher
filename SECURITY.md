# Security

History-Dispatcher is local-only by design. Payloads are encrypted with an
AES-256-GCM key retrieved from the user Secret Service; there is no plaintext
fallback. The control endpoint is an owner-only Unix socket and all applet
reads are bounded to the versioned status snapshot.

Please report security issues privately to the repository owner rather than
opening a public issue with exploit details. Include the affected commit,
reproduction steps, and whether the issue involves payload confidentiality,
queue integrity, or Cinnamon process safety.
