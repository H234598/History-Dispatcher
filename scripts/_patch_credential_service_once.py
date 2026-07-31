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
        "from .config_manager_v2 import (\n"
        "    ConfigManagerV2,\n"
        "    ConfigV2ApplyError,\n"
        "    ConfigV2ValidationError,\n"
        ")\n",
        "from .config_manager_v2 import (\n"
        "    ConfigManagerV2,\n"
        "    ConfigV2ApplyError,\n"
        "    ConfigV2ValidationError,\n"
        ")\n"
        "from .credential_manager import (\n"
        "    CredentialApplyError,\n"
        "    CredentialManager,\n"
        "    CredentialValidationError,\n"
        ")\n",
        label="credential imports",
    )
    source = replace_once(
        source,
        "from .status_v2 import CredentialStatus\n",
        "from .status_v2 import CredentialStatus\n"
        "from .telegram_secrets import NativeTelegramSecretStore\n",
        label="secret store import",
    )
    source = replace_once(
        source,
        '    "config.apply",\n'
        '    "collector.collect", "admin.preview", "admin.execute", "audit.query",\n',
        '    "config.apply",\n'
        '    "credential.get_status", "credential.preview_apply",\n'
        '    "credential.apply",\n'
        '    "collector.collect", "admin.preview", "admin.execute", "audit.query",\n',
        label="operation allowlist",
    )
    source = replace_once(
        source,
        '    "config.validate_patch", "config.apply", "collector.collect",\n',
        '    "config.validate_patch", "config.apply", "credential.apply",\n'
        '    "collector.collect",\n',
        label="durable idempotency",
    )
    source = replace_once(
        source,
        '    {"provider.v2.claim", "provider.v2.reclaim", "config.preview_apply"}\n',
        '    {\n'
        '        "provider.v2.claim",\n'
        '        "provider.v2.reclaim",\n'
        '        "config.preview_apply",\n'
        '        "credential.preview_apply",\n'
        '    }\n',
        label="one-shot operations",
    )
    source = replace_once(
        source,
        'CONFIG_V2_REQUEST_ID_REQUIRED = frozenset(\n'
        '    {"config.validate_patch", "config.preview_apply"}\n'
        ')\n',
        'CONFIG_V2_REQUEST_ID_REQUIRED = frozenset(\n'
        '    {"config.validate_patch", "config.preview_apply"}\n'
        ')\n'
        'CREDENTIAL_REQUEST_ID_REQUIRED = frozenset(\n'
        '    {"credential.preview_apply", "credential.apply"}\n'
        ')\n',
        label="credential request ids",
    )
    source = replace_once(
        source,
        "class DispatcherService:\n"
        "    def __init__(self, config: DispatcherConfig, *, key_provider: SecretServiceKeyProvider | None = None) -> None:\n"
        "        self.config = config\n"
        "        self.key_provider = key_provider or SecretServiceKeyProvider()\n",
        "class DispatcherService:\n"
        "    def __init__(\n"
        "        self,\n"
        "        config: DispatcherConfig,\n"
        "        *,\n"
        "        key_provider: SecretServiceKeyProvider | None = None,\n"
        "        telegram_secret_store: NativeTelegramSecretStore | None = None,\n"
        "    ) -> None:\n"
        "        self.config = config\n"
        "        self.key_provider = key_provider or SecretServiceKeyProvider()\n"
        "        self._telegram_secret_store = (\n"
        "            telegram_secret_store or NativeTelegramSecretStore()\n"
        "        )\n",
        label="constructor injection",
    )
    source = replace_once(
        source,
        "        self._config_manager_v2: ConfigManagerV2 | None = None\n",
        "        self._config_manager_v2: ConfigManagerV2 | None = None\n"
        "        self._credential_manager: CredentialManager | None = None\n",
        label="credential manager slot",
    )
    source = replace_once(
        source,
        "    def _config_v2(self) -> ConfigManagerV2:\n",
        "    def _credentials(self) -> CredentialManager:\n"
        "        if self._credential_manager is None:\n"
        "            self._credential_manager = CredentialManager(\n"
        "                self.config,\n"
        "                database_path=self.config.database_path,\n"
        "                key_provider=self.key_provider,\n"
        "                secret_store=self._telegram_secret_store,\n"
        "            )\n"
        "        return self._credential_manager\n\n"
        "    def _credential_status(self) -> CredentialStatus:\n"
        "        if not self.config.telegram_credential_ref:\n"
        "            return CredentialStatus(configured=False)\n"
        "        try:\n"
        "            bot = self._credentials().get_status()[\"bot\"]\n"
        "            if not isinstance(bot, dict):\n"
        "                return CredentialStatus(configured=False)\n"
        "            return CredentialStatus(\n"
        "                configured=bool(bot.get(\"configured\")),\n"
        "                last_changed=(\n"
        "                    str(bot.get(\"last_changed\"))\n"
        "                    if bot.get(\"last_changed\")\n"
        "                    else None\n"
        "                ),\n"
        "            )\n"
        "        except Exception:\n"
        "            return CredentialStatus(configured=False)\n\n"
        "    def _config_v2(self) -> ConfigManagerV2:\n",
        label="lazy credential manager",
    )
    source = replace_once(
        source,
        "            credential=CredentialStatus(configured=False),\n",
        "            credential=self._credential_status(),\n",
        label="credential status metadata",
    )
    source = replace_once(
        source,
        "        if (\n"
        "            operation in CONFIG_V2_REQUEST_ID_REQUIRED or config_v2_apply\n"
        "        ) and not request_id:\n"
        "            return self._error(\n"
        "                \"invalid_request_id\",\n"
        "                \"Config v2 mutations require a request_id\",\n"
        "            )\n\n",
        "        if (\n"
        "            operation in CONFIG_V2_REQUEST_ID_REQUIRED or config_v2_apply\n"
        "        ) and not request_id:\n"
        "            return self._error(\n"
        "                \"invalid_request_id\",\n"
        "                \"Config v2 mutations require a request_id\",\n"
        "            )\n"
        "        if operation in CREDENTIAL_REQUEST_ID_REQUIRED and not request_id:\n"
        "            return self._error(\n"
        "                \"invalid_request_id\",\n"
        "                \"credential mutations require a request_id\",\n"
        "            )\n\n",
        label="credential request id enforcement",
    )
    source = replace_once(
        source,
        "                (ProviderApiValidationError, ConfigV2ValidationError),\n",
        "                (\n"
        "                    ProviderApiValidationError,\n"
        "                    ConfigV2ValidationError,\n"
        "                    CredentialValidationError,\n"
        "                ),\n",
        label="credential validation release",
    )
    source = replace_once(
        source,
        '        if operation == "config.get_redacted":\n'
        "            return self._config_v2().get_redacted()\n",
        '        if operation == "credential.get_status":\n'
        "            if body:\n"
        "                raise CredentialValidationError(\n"
        '                    "credential.get_status accepts an empty body"\n'
        "                )\n"
        "            return self._credentials().get_status()\n"
        '        if operation == "credential.preview_apply":\n'
        "            allowed = {\n"
        '                "action",\n'
        '                "secret_kind",\n'
        '                "profile_ref",\n'
        '                "secret_value",\n'
        "            }\n"
        "            required = {\"action\", \"secret_kind\", \"profile_ref\"}\n"
        "            if not required <= set(body) or set(body) - allowed:\n"
        "                raise CredentialValidationError(\n"
        '                    "credential.preview_apply body is invalid"\n'
        "                )\n"
        "            return self._credentials().preview_apply(\n"
        "                action=str(body.get(\"action\") or \"\"),\n"
        "                secret_kind=str(body.get(\"secret_kind\") or \"\"),\n"
        "                profile_ref=body.get(\"profile_ref\"),\n"
        "                secret_value=body.get(\"secret_value\"),\n"
        "            ).as_dict()\n"
        '        if operation == "credential.apply":\n'
        "            required = {\"preview_token\", \"fingerprint\", \"confirmation\"}\n"
        "            if set(body) != required:\n"
        "                raise CredentialApplyError(\n"
        '                    "credential.apply requires preview_token, fingerprint, "\n'
        '                    "and confirmation"\n'
        "                )\n"
        "            return self._credentials().apply_preview(\n"
        "                preview_token=str(body.get(\"preview_token\") or \"\"),\n"
        "                fingerprint=str(body.get(\"fingerprint\") or \"\"),\n"
        "                confirmation=str(body.get(\"confirmation\") or \"\"),\n"
        "                actor=f\"uid:{os.getuid()}\",\n"
        "            )\n"
        '        if operation == "config.get_redacted":\n'
        "            return self._config_v2().get_redacted()\n",
        label="credential dispatch",
    )
    source = replace_once(
        source,
        "                self.config = self._config_v2().config\n"
        "                return result\n",
        "                self.config = self._config_v2().config\n"
        "                if self._credential_manager is not None:\n"
        "                    self._credential_manager.replace_config(self.config)\n"
        "                return result\n",
        label="config v2 credential sync",
    )
    source = replace_once(
        source,
        "            if self._config_manager_v2 is not None:\n"
        "                self._config_manager_v2.replace_config(self.config)\n"
        "            return {\"ok\": True, \"config\": public_config(self.config), \"restart_required\": False}\n",
        "            if self._config_manager_v2 is not None:\n"
        "                self._config_manager_v2.replace_config(self.config)\n"
        "            if self._credential_manager is not None:\n"
        "                self._credential_manager.replace_config(self.config)\n"
        "            return {\"ok\": True, \"config\": public_config(self.config), \"restart_required\": False}\n",
        label="legacy config credential sync",
    )
    SERVICE.write_text(source, encoding="utf-8")


def patch_architecture() -> None:
    source = ARCHITECTURE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '        "config.apply",\n'
        '        "collector.collect",\n',
        '        "config.apply",\n'
        '        "credential.get_status",\n'
        '        "credential.preview_apply",\n'
        '        "credential.apply",\n'
        '        "collector.collect",\n',
        label="architecture credential operations",
    )
    ARCHITECTURE.write_text(source, encoding="utf-8")


def main() -> None:
    patch_service()
    patch_architecture()


if __name__ == "__main__":
    main()
