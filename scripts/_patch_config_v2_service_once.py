from __future__ import annotations

from pathlib import Path


SERVICE = Path("history_dispatcher/service.py")
ARCHITECTURE = Path("tests/test_architecture_contract.py")


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def patch_service() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "from .crypto import SecretServiceKeyProvider\n",
        "from .crypto import SecretServiceKeyProvider\n"
        "from .config_manager_v2 import (\n"
        "    ConfigManagerV2,\n"
        "    ConfigV2ApplyError,\n"
        "    ConfigV2ValidationError,\n"
        ")\n",
        label="config manager imports",
    )
    source = replace_once(
        source,
        '    "delivery.record", "config.get", "config.validate", "config.apply",\n',
        '    "delivery.record", "config.get", "config.get_redacted",\n'
        '    "config.validate", "config.validate_patch", "config.preview_apply",\n'
        '    "config.apply",\n',
        label="operation allowlist",
    )
    source = replace_once(
        source,
        '    "history.append", "dispatch.claim", "dispatch.complete", "dispatch.retry", "delivery.record",\n'
        '    "config.apply", "collector.collect", "admin.execute", "migration.import_legacy",\n',
        '    "history.append", "dispatch.claim", "dispatch.complete", "dispatch.retry", "delivery.record",\n'
        '    "config.validate_patch", "config.apply", "collector.collect",\n'
        '    "admin.execute", "migration.import_legacy",\n',
        label="idempotent operations",
    )
    source = replace_once(
        source,
        'ONE_SHOT_SENSITIVE_OPERATIONS = frozenset({"provider.v2.claim", "provider.v2.reclaim"})\n'
        'PROVIDER_REQUEST_ID_REQUIRED = frozenset(PROVIDER_API_OPERATIONS)\n',
        'ONE_SHOT_SENSITIVE_OPERATIONS = frozenset(\n'
        '    {"provider.v2.claim", "provider.v2.reclaim", "config.preview_apply"}\n'
        ')\n'
        'PROVIDER_REQUEST_ID_REQUIRED = frozenset(PROVIDER_API_OPERATIONS)\n'
        'CONFIG_V2_REQUEST_ID_REQUIRED = frozenset(\n'
        '    {"config.validate_patch", "config.preview_apply"}\n'
        ')\n',
        label="one-shot operations",
    )
    source = replace_once(
        source,
        "        self._provider_api: ProviderApiV2 | None = None\n",
        "        self._provider_api: ProviderApiV2 | None = None\n"
        "        self._config_manager_v2: ConfigManagerV2 | None = None\n",
        label="manager slot",
    )
    source = replace_once(
        source,
        "    def _provider_worker_api(self) -> ProviderApiV2:\n",
        "    def _config_v2(self) -> ConfigManagerV2:\n"
        "        if self._config_manager_v2 is None:\n"
        "            self._config_manager_v2 = ConfigManagerV2(\n"
        "                self.config,\n"
        "                database_path=self.config.database_path,\n"
        "                key_provider=self.key_provider,\n"
        "            )\n"
        "        return self._config_manager_v2\n\n"
        "    def _provider_worker_api(self) -> ProviderApiV2:\n",
        label="lazy manager",
    )
    source = replace_once(
        source,
        '            telegram_provider="teebotus",\n',
        '            telegram_provider=self.config.telegram_provider.value,\n',
        label="status provider",
    )
    source = replace_once(
        source,
        "        if operation in PROVIDER_REQUEST_ID_REQUIRED and not request_id:\n"
        "            return self._error(\n"
        "                \"invalid_request_id\",\n"
        "                \"provider v2 mutations require a request_id\",\n"
        "            )\n\n",
        "        config_v2_apply = (\n"
        "            operation == \"config.apply\"\n"
        "            and any(\n"
        "                key in body\n"
        "                for key in (\n"
        "                    \"preview_token\",\n"
        "                    \"fingerprint\",\n"
        "                    \"confirmation\",\n"
        "                )\n"
        "            )\n"
        "        )\n"
        "        if operation in PROVIDER_REQUEST_ID_REQUIRED and not request_id:\n"
        "            return self._error(\n"
        "                \"invalid_request_id\",\n"
        "                \"provider v2 mutations require a request_id\",\n"
        "            )\n"
        "        if (\n"
        "            operation in CONFIG_V2_REQUEST_ID_REQUIRED or config_v2_apply\n"
        "        ) and not request_id:\n"
        "            return self._error(\n"
        "                \"invalid_request_id\",\n"
        "                \"Config v2 mutations require a request_id\",\n"
        "            )\n\n",
        label="request id checks",
    )
    source = replace_once(
        source,
        "            if isinstance(operation_exception, ProviderApiValidationError):\n",
        "            if isinstance(\n"
        "                operation_exception,\n"
        "                (ProviderApiValidationError, ConfigV2ValidationError),\n"
        "            ):\n",
        label="one-shot validation release",
    )
    source = replace_once(
        source,
        '        if operation == "status.get_redacted":\n'
        "            return self._status_v2()\n",
        '        if operation == "status.get_redacted":\n'
        "            return self._status_v2()\n"
        '        if operation == "config.get_redacted":\n'
        "            return self._config_v2().get_redacted()\n"
        '        if operation == "config.validate_patch":\n'
        '            if set(body) != {"patch"}:\n'
        "                raise ConfigV2ValidationError(\n"
        '                    "config.validate_patch accepts only patch"\n'
        "                )\n"
        "            patch = self._config_v2().validate_patch(body.get(\"patch\"))\n"
        "            return {\n"
        "                \"schema_version\": 2,\n"
        "                \"patch\": patch.canonical_dict(),\n"
        "            }\n"
        '        if operation == "config.preview_apply":\n'
        '            if set(body) != {"expected_revision", "patch"}:\n'
        "                raise ConfigV2ValidationError(\n"
        '                    "config.preview_apply requires expected_revision and patch"\n'
        "                )\n"
        "            return self._config_v2().preview_apply(\n"
        "                expected_revision=str(\n"
        "                    body.get(\"expected_revision\") or \"\"\n"
        "                ),\n"
        "                patch=body.get(\"patch\"),\n"
        "            ).as_dict()\n",
        label="config v2 dispatch",
    )
    old_apply = """        if operation == "config.apply":
            values = body.get("values")
            if not isinstance(values, dict):
                return {"ok": False, "error": "values_must_be_object"}
            expected_revision = str(body.get("expected_revision") or "").strip()
            if expected_revision and expected_revision != config_revision(self.config):
                return {"ok": False, "error": "config_revision_changed", "config_revision": config_revision(self.config)}
            new_config = apply_safe_values(self.config, values)
            write_config(new_config)
            self.config = load_config(new_config.config_path)
            return {"ok": True, "config": public_config(self.config), "restart_required": False}
"""
    new_apply = """        if operation == "config.apply":
            v2_keys = {
                "expected_revision",
                "preview_token",
                "fingerprint",
                "confirmation",
            }
            if any(key in body for key in v2_keys - {"expected_revision"}):
                if set(body) != v2_keys:
                    raise ConfigV2ApplyError(
                        "Config v2 apply requires expected_revision, preview_token, "
                        "fingerprint, and confirmation"
                    )
                result = self._config_v2().apply_preview(
                    expected_revision=str(body.get("expected_revision") or ""),
                    preview_token=str(body.get("preview_token") or ""),
                    fingerprint=str(body.get("fingerprint") or ""),
                    confirmation=str(body.get("confirmation") or ""),
                    actor=f"uid:{os.getuid()}",
                )
                self.config = self._config_v2().config
                return result
            values = body.get("values")
            if not isinstance(values, dict):
                return {"ok": False, "error": "values_must_be_object"}
            expected_revision = str(body.get("expected_revision") or "").strip()
            if expected_revision and expected_revision != config_revision(self.config):
                return {"ok": False, "error": "config_revision_changed", "config_revision": config_revision(self.config)}
            new_config = apply_safe_values(self.config, values)
            write_config(new_config)
            self.config = load_config(new_config.config_path)
            if self._config_manager_v2 is not None:
                self._config_manager_v2.replace_config(self.config)
            return {"ok": True, "config": public_config(self.config), "restart_required": False}
"""
    source = replace_once(
        source,
        old_apply,
        new_apply,
        label="config apply dispatch",
    )
    SERVICE.write_text(source, encoding="utf-8")


def patch_architecture() -> None:
    source = ARCHITECTURE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '        "config.get",\n'
        '        "config.validate",\n'
        '        "config.apply",\n',
        '        "config.get",\n'
        '        "config.get_redacted",\n'
        '        "config.validate",\n'
        '        "config.validate_patch",\n'
        '        "config.preview_apply",\n'
        '        "config.apply",\n',
        label="architecture allowlist",
    )
    ARCHITECTURE.write_text(source, encoding="utf-8")


def main() -> None:
    patch_service()
    patch_architecture()


if __name__ == "__main__":
    main()
