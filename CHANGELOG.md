# Changelog

## 0.1.3 - 2026-07-10

- Keep the long-lived control socket alive across collector timer runs by
  letting only the main service own the shared systemd runtime directories.

## 0.1.2 - 2026-07-10

- Enforce `dispatch.enabled` and `dispatch.paused` at the claim API boundary.
  Paused or disabled dispatch now fails closed without changing queue state.

## 0.1.1 - 2026-07-10

- Add a complete strict `config.example.toml` for service and applet setup.

## 0.1.0 - 2026-07-10

- Standalone encrypted SQLite history queue and versioned Unix-socket API.
- Bounded Codex JSONL collector, claims, retries, receipts, tombstones, and
  optimistic configuration updates.
- Optional TeeBotus bridge, callback spool, Dispatcher Cinnamon applet, and
  optional TB-Applet mirror.
- Xephyr/Bubblewrap isolated Cinnamon runner with rootless Xephyr fallback.
