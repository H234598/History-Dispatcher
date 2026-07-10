#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPLET_UUID = "history-dispatcher@H234598"
TEEBOTUS_UUID = "teebotus@H234598"
TEEBOTUS_ROOT = ROOT.parent / "TeeBotus"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Cinnamon applet tests in isolated Xephyr/bubblewrap.")
    parser.add_argument("--xephyr", default="Xephyr")
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--applet", type=Path, default=ROOT / "files" / APPLET_UUID)
    parser.add_argument("--applets", choices=("history-dispatcher", "teebotus", "both"), default="history-dispatcher")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)
    if shutil.which(args.xephyr) is None and not Path(args.xephyr).exists():
        raise SystemExit("Xephyr executable not found")
    if shutil.which("bwrap") is None:
        raise SystemExit("bubblewrap executable not found")
    with tempfile.TemporaryDirectory(prefix="history-dispatcher-cinnamon-") as raw_temp:
        temp = Path(raw_temp)
        result = _run_isolated(args, temp)
        if args.keep_temp:
            kept = Path(temp.parent) / f"{temp.name}-kept"
            shutil.copytree(temp, kept)
            result["kept_temp"] = str(kept)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["ok"] else 1


def _run_isolated(args: argparse.Namespace, temp: Path) -> dict[str, object]:
    home = temp / "home"
    runtime = temp / "runtime"
    xdg_config = temp / "config"
    xdg_data = temp / "data"
    xdg_cache = temp / "cache"
    xdg_state = temp / "state"
    for path in (home, runtime, xdg_config, xdg_data, xdg_cache, xdg_state):
        path.mkdir(mode=0o700, parents=True)
    if args.applets == "history-dispatcher":
        applet_specs = [(APPLET_UUID, args.applet)]
    elif args.applets == "teebotus":
        applet_specs = [(TEEBOTUS_UUID, TEEBOTUS_ROOT / "files" / TEEBOTUS_UUID)]
    else:
        applet_specs = [
            (APPLET_UUID, ROOT / "files" / APPLET_UUID),
            (TEEBOTUS_UUID, TEEBOTUS_ROOT / "files" / TEEBOTUS_UUID),
        ]
    for applet_uuid, applet_source in applet_specs:
        applet_target = home / ".local/share/cinnamon/applets" / applet_uuid
        applet_target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copytree(applet_source, applet_target)
    status_dir = runtime / "history-dispatcher"
    status_dir.mkdir(mode=0o700)
    (status_dir / "status-v1.json").write_text(json.dumps({
        "schema_version": 1,
        "service": "history-dispatcher",
        "version": "0.1.0-test",
        "ok": True,
        "total": 2,
        "queued": 1,
        "oldest_queued_at": "2026-07-10T12:00:00+00:00",
        "collector": {"enabled": True, "sources": 1},
        "dispatch": {"enabled": True, "paused": False, "batch_size": 20},
        "queue_preview": [{"id": "test-item-1", "status": "queued", "kind": "codex_run_summary", "created_at": "2026-07-10T12:00:00+00:00"}],
    }, separators=(",", ":")), encoding="utf-8")
    os.chmod(status_dir / "status-v1.json", 0o600)
    auth = home / ".Xauthority"
    cookie = secrets.token_hex(16)
    display = None
    xephyr = None
    for candidate in range(90, 120):
        subprocess.run(["xauth", "-f", str(auth), "add", f":{candidate}", ".", cookie], check=True, capture_output=True)
        process = subprocess.Popen([
            str(args.xephyr), f":{candidate}", "-screen", "1280x800", "-nolisten", "tcp", "-auth", str(auth), "-noreset",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        time.sleep(0.8)
        if process.poll() is None:
            display = candidate
            xephyr = process
            break
        process.wait(timeout=2)
    if xephyr is None or display is None:
        return {"ok": False, "error": "could not start Xephyr"}
    env = {
        "DISPLAY": f":{display}",
        "XAUTHORITY": "/home/tester/.Xauthority",
        "HOME": "/home/tester",
        "USER": "tester",
        "LOGNAME": "tester",
        "XDG_CONFIG_HOME": "/home/tester/.config",
        "XDG_DATA_HOME": "/home/tester/.local/share",
        "XDG_CACHE_HOME": "/home/tester/.cache",
        "XDG_STATE_HOME": "/home/tester/.local/state",
        "XDG_RUNTIME_DIR": "/home/tester/runtime",
        "XDG_CURRENT_DESKTOP": "X-Cinnamon",
        "XDG_SESSION_TYPE": "x11",
        "GSETTINGS_BACKEND": "dconf",
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "MESA_LOADER_DRIVER_OVERRIDE": "llvmpipe",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    enabled_applets = [
        f"panel1:right:{index}:{applet_uuid}:0"
        for index, (applet_uuid, _source) in enumerate(applet_specs)
    ]
    enabled_applets_json = json.dumps(enabled_applets, separators=(",", ":"))
    bwrap = [
        "bwrap", "--die-with-parent", "--new-session", "--unshare-all",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/etc", "/etc",
        "--ro-bind", "/var", "/var",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/sbin", "/sbin",
        "--proc", "/proc", "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--bind", str(home), "/home/tester",
        "--bind", str(runtime), "/home/tester/runtime",
        "--ro-bind", str(ROOT), "/home/tester/History-Dispatcher",
        "--ro-bind", str(TEEBOTUS_ROOT), "/home/tester/TeeBotus",
        "--ro-bind", "/tmp/.X11-unix", "/tmp/.X11-unix",
        "--setenv", "DISPLAY", env["DISPLAY"],
        "--setenv", "XAUTHORITY", env["XAUTHORITY"],
        "--setenv", "HOME", env["HOME"],
        "--setenv", "USER", env["USER"],
        "--setenv", "LOGNAME", env["LOGNAME"],
        "--setenv", "XDG_CONFIG_HOME", env["XDG_CONFIG_HOME"],
        "--setenv", "XDG_DATA_HOME", env["XDG_DATA_HOME"],
        "--setenv", "XDG_CACHE_HOME", env["XDG_CACHE_HOME"],
        "--setenv", "XDG_STATE_HOME", env["XDG_STATE_HOME"],
        "--setenv", "XDG_RUNTIME_DIR", env["XDG_RUNTIME_DIR"],
        "--setenv", "XDG_CURRENT_DESKTOP", env["XDG_CURRENT_DESKTOP"],
        "--setenv", "XDG_SESSION_TYPE", env["XDG_SESSION_TYPE"],
        "--setenv", "GSETTINGS_BACKEND", env["GSETTINGS_BACKEND"],
        "--setenv", "LIBGL_ALWAYS_SOFTWARE", env["LIBGL_ALWAYS_SOFTWARE"],
        "--setenv", "MESA_LOADER_DRIVER_OVERRIDE", env["MESA_LOADER_DRIVER_OVERRIDE"],
        "--setenv", "PATH", env["PATH"],
        "--", "dbus-run-session", "--", "sh", "-c",
        f"dbus-daemon --session --address=unix:path=\"$XDG_RUNTIME_DIR/system-bus\" --fork; export DBUS_SYSTEM_BUS_ADDRESS=unix:path=\"$XDG_RUNTIME_DIR/system-bus\"; gsettings set org.cinnamon enabled-applets '{enabled_applets_json}'; exec cinnamon --display \"$DISPLAY\" --sm-disable",
    ]
    cinnamon = subprocess.Popen(bwrap, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    cinnamon_pid = cinnamon.pid
    try:
        cinnamon.wait(timeout=max(5.0, float(args.duration)))
        returncode = cinnamon.returncode
        ok = False
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        ok = cinnamon.poll() is None
        cinnamon.send_signal(signal.SIGTERM)
        try:
            cinnamon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cinnamon.kill()
            cinnamon.wait(timeout=5)
        returncode = cinnamon.returncode
    finally:
        if xephyr.poll() is None:
            xephyr.terminate()
            try:
                xephyr.wait(timeout=3)
            except subprocess.TimeoutExpired:
                xephyr.kill()
                xephyr.wait(timeout=3)
    stdout, stderr = cinnamon.communicate(timeout=2)
    exception_lines = [
        line[-500:]
        for line in stderr.splitlines()
        if any(marker in line for marker in ("JS ERROR", "UnhandledPromise", "TypeError:", "ReferenceError:", "SyntaxError:"))
    ]
    loaded_applets = {
        applet_uuid: f"Loaded applet {applet_uuid}" in stderr
        for applet_uuid, _source in applet_specs
    }
    return {
        "ok": bool(ok) and not exception_lines and all(loaded_applets.values()),
        "loaded_applets": loaded_applets,
        "unhandled_js_exceptions": exception_lines[:50],
        "cinnamon_pid": cinnamon_pid,
        "display": display,
        "duration_seconds": float(args.duration),
        "timed_out_as_expected": timed_out,
        "cinnamon_returncode": returncode,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-8000:],
    }


if __name__ == "__main__":
    raise SystemExit(main())
