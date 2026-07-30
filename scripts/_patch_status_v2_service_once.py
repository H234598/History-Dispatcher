from __future__ import annotations

from pathlib import Path


SERVICE = Path("history_dispatcher/service.py")
ARCHITECTURE_TEST = Path("tests/test_architecture_contract.py")


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def patch_service() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "from .store import DispatcherStore\n",
        "from .store import DispatcherStore\n"
        "from .status_api_v2 import build_redacted_status_response\n"
        "from .status_runtime_v2 import build_runtime_health_status\n"
        "from .status_snapshot_v2 import write_status_v2_snapshot\n"
        "from .status_v2 import CredentialStatus\n",
        label="service imports",
    )
    source = _replace_once(
        source,
        '    "protocol.describe", "health.get", "status.get", "report.get",\n',
        '    "protocol.describe", "health.get", "status.get", '
        '"status.get_redacted", "report.get",\n',
        label="operation allowlist",
    )
    source = _replace_once(
        source,
        "        return status\n\n    def _write_snapshot(self) -> None:\n",
        "        return status\n\n"
        "    def _status_v2(self) -> dict[str, Any]:\n"
        "        queue = self.store.status()\n"
        "        status = build_runtime_health_status(\n"
        "            database_path=self.config.database_path,\n"
        "            telegram_provider=\"teebotus\",\n"
        "            credential=CredentialStatus(configured=False),\n"
        "            queue_counts=dict(queue.get(\"status_counts\", {})),\n"
        "            generated_at=_timestamp(),\n"
        "        )\n"
        "        return build_redacted_status_response(status).as_dict()\n\n"
        "    def _write_snapshot(self) -> None:\n"
        "        write_status_v2_snapshot(\n"
        "            self.config.runtime_dir / \"status-v2.json\",\n"
        "            self._status_v2(),\n"
        "        )\n",
        label="status-v2 builder and snapshot",
    )
    source = _replace_once(
        source,
        '        if operation in {"health.get", "status.get", "report.get"}:\n'
        "            return self._status()\n",
        '        if operation == "status.get_redacted":\n'
        "            return self._status_v2()\n"
        '        if operation in {"health.get", "status.get", "report.get"}:\n'
        "            return self._status()\n",
        label="status-v2 dispatch",
    )
    SERVICE.write_text(source, encoding="utf-8")


def patch_architecture_test() -> None:
    source = ARCHITECTURE_TEST.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        '        "status.get",\n        "report.get",\n',
        '        "status.get",\n        "status.get_redacted",\n        "report.get",\n',
        label="architecture operation tuple",
    )
    ARCHITECTURE_TEST.write_text(source, encoding="utf-8")


def main() -> None:
    patch_service()
    patch_architecture_test()


if __name__ == "__main__":
    main()
