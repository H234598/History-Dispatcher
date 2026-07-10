from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def _unit_path(value: str, name: str) -> str:
    text = str(value).strip()
    if not text or any(ord(char) < 0x20 for char in text):
        raise ValueError(f"{name} is invalid")
    return text


def render_units(*, python: str, config: Path, service_name: str = "history-dispatcher.service", collector_service_name: str = "history-dispatcher-collector.service", timer_name: str = "history-dispatcher-collector.timer", interval: str = "300s") -> dict[str, str]:
    executable = _unit_path(python, "python")
    config_text = _unit_path(str(config.expanduser()), "config")
    service = f"""[Unit]
Description=History-Dispatcher
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory={Path(executable).parent.parent.parent}
ExecStart={executable} -m history_dispatcher --config {config_text} serve
Restart=on-failure
RestartSec=5s
StateDirectory=history-dispatcher
StateDirectoryMode=0700
RuntimeDirectory=history-dispatcher
RuntimeDirectoryMode=0700
ConfigurationDirectory=history-dispatcher
ConfigurationDirectoryMode=0700
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.local/state/history-dispatcher %h/.config/history-dispatcher %t/history-dispatcher
RestrictAddressFamilies=AF_UNIX AF_FILE
RestrictNamespaces=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
UMask=0077

[Install]
WantedBy=default.target
"""
    collector = f"""[Unit]
Description=History-Dispatcher Codex collector
After=history-dispatcher.service
Requires=history-dispatcher.service

[Service]
Type=oneshot
ExecStart={executable} -m history_dispatcher --config {config_text} collect
# The long-lived service owns these directories.  Re-declaring
# RuntimeDirectory/StateDirectory here would let systemd remove the shared
# runtime socket when this oneshot collector exits.
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.local/state/history-dispatcher %h/.config/history-dispatcher %t/history-dispatcher
RestrictAddressFamilies=AF_UNIX AF_FILE
RestrictNamespaces=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
UMask=0077
"""
    timer = f"""[Unit]
Description=Run History-Dispatcher Codex collector periodically

[Timer]
OnBootSec=2min
OnUnitActiveSec={interval}
Persistent=true
RandomizedDelaySec=30s

[Install]
WantedBy=timers.target
"""
    return {
        service_name: service,
        collector_service_name: collector,
        timer_name: timer,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render/install History-Dispatcher user units.")
    parser.add_argument("--python", default=str(Path(__file__).resolve().parents[1] / ".venv-py313/bin/python"))
    parser.add_argument("--config", type=Path, default=Path.home() / ".config/history-dispatcher/config.toml")
    parser.add_argument("--unit-dir", type=Path, default=Path.home() / ".config/systemd/user")
    parser.add_argument("--interval", default="300s")
    parser.add_argument("--print", action="store_true", dest="print_only")
    parser.add_argument("--enable", action="store_true")
    args = parser.parse_args(argv)
    units = render_units(python=args.python, config=args.config, interval=args.interval)
    if args.print_only:
        for name, text in units.items():
            print(f"# {name}")
            print(text, end="")
        return 0
    args.unit_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, text in units.items():
        target = args.unit_dir / name
        target.write_text(text, encoding="utf-8")
        os.chmod(target, 0o600)
        print(f"wrote {target}")
    if args.enable:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "history-dispatcher.service"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "history-dispatcher-collector.timer"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
