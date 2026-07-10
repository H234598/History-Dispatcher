from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import load_config, public_config
from .protocol import request
from .service import DispatcherService, call_socket, serve
from .crypto import StaticKeyProvider


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="history-dispatcher")
    parser.add_argument("--config", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    config = sub.add_parser("config")
    config.add_argument("action", choices=("check", "show"))
    protocol = sub.add_parser("protocol")
    protocol.add_argument("--json", action="store_true")
    append = sub.add_parser("append")
    append.add_argument("--source", default="manual")
    append.add_argument("--kind", default="history")
    append.add_argument("--dedupe-key", default="")
    append.add_argument("--target-group", default="status_admins")
    append.add_argument("--project", default="")
    append.add_argument("--payload-json", required=True)
    query = sub.add_parser("query")
    query.add_argument("--status", default="")
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--include-payload", action="store_true")
    claim = sub.add_parser("claim")
    claim.add_argument("--worker-id", required=True)
    claim.add_argument("--limit", type=int, default=20)
    complete = sub.add_parser("complete")
    complete.add_argument("--item-id", required=True)
    complete.add_argument("--worker-id", required=True)
    complete.add_argument("--recipient-results-json", default="[]")
    complete.add_argument("--reason", default="")
    retry = sub.add_parser("retry")
    retry.add_argument("--item-id", required=True)
    retry.add_argument("--reason", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_config(args.config)
    if args.command == "serve":
        serve(config)
        return 0
    if args.command == "config":
        if args.action == "check":
            _json_print({"ok": True, "config": public_config(config)})
        else:
            _json_print(public_config(config))
        return 0
    if args.command == "status":
        response = _call(config, "status.get", {})
        if response.get("ok"):
            _json_print(response["data"])
            return 0
        snapshot = config.snapshot_path
        if snapshot.exists():
            print(snapshot.read_text(encoding="utf-8"))
            return 0
        _json_print(response)
        return 1
    if args.command == "protocol":
        response = _call(config, "protocol.describe", {})
        _json_print(response.get("data", response))
        return 0 if response.get("ok") else 1
    if args.command == "append":
        try:
            payload = json.loads(args.payload_json)
        except json.JSONDecodeError as exc:
            print(f"invalid payload JSON: {exc}", file=sys.stderr)
            return 2
        response = _call(config, "history.append", {
            "source": args.source,
            "kind": args.kind,
            "dedupe_key": args.dedupe_key,
            "target_group": args.target_group,
            "project": args.project,
            "payload": payload,
        })
        _json_print(response.get("data", response))
        return 0 if response.get("ok") else 1
    if args.command == "query":
        response = _call(config, "history.query", {
            "status": args.status,
            "limit": args.limit,
            "include_payload": args.include_payload,
        })
        _json_print(response.get("data", response))
        return 0 if response.get("ok") else 1
    if args.command == "claim":
        response = _call(config, "dispatch.claim", {"worker_id": args.worker_id, "limit": args.limit})
        _json_print(response.get("data", response))
        return 0 if response.get("ok") else 1
    if args.command == "complete":
        try:
            recipient_results = json.loads(args.recipient_results_json)
        except json.JSONDecodeError as exc:
            print(f"invalid recipient results JSON: {exc}", file=sys.stderr)
            return 2
        response = _call(config, "dispatch.complete", {
            "item_id": args.item_id,
            "worker_id": args.worker_id,
            "recipient_results": recipient_results,
            "reason": args.reason,
        })
        _json_print(response.get("data", response))
        return 0 if response.get("ok") else 1
    if args.command == "retry":
        response = _call(config, "dispatch.retry", {"item_id": args.item_id, "reason": args.reason})
        _json_print(response.get("data", response))
        return 0 if response.get("ok") else 1
    return 2


def _call(config, operation: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        return call_socket(config.socket_path, request(operation, body), max_bytes=config.frame_limit_bytes)
    except OSError:
        if operation in {"status.get", "health.get"}:
            service = DispatcherService(config, key_provider=StaticKeyProvider(b"\x00" * 32))
            return {"ok": True, "data": service._status()}
        return {"ok": False, "error": {"code": "dispatcher_unavailable", "message": "control socket unavailable"}}


if __name__ == "__main__":
    raise SystemExit(main())

