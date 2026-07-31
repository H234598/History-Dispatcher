from __future__ import annotations

from pathlib import Path


SPEC = Path(
    "docs/superpowers/specs/2026-07-31-shared-telegram-fault-canary-design.md"
)


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    source = SPEC.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "JSON is written\nwith UTF-8, LF line endings, two-space indentation, sorted object keys and one\ntrailing newline.",
        "JSON is written with UTF-8, LF line endings, two-space indentation, the\nschema-defined field order and one trailing newline. Code examples describe\nsemantics; only the committed canonical file defines the digest-bearing byte\norder.",
        label="canonical formatting",
    )
    source = replace_once(
        source,
        "Every normalized recipient outcome contains exactly:\n\n```text\nstatus\npossible_duplicate\nreason_code\nmessage_ref_required\n```\n\nAllowed normalized statuses:\n\n```text\naccepted\ndelivered\nacknowledged\nfailed\nfailed_terminal\nskipped\npossible_duplicate\n```",
        "Every transport-neutral recipient expectation contains exactly:\n\n```text\nstate_class\npossible_duplicate\nreason_code\nmessage_ref_required\nminimum_success_rank\n```\n\nAllowed `state_class` values:\n\n```text\nsuccess\nretryable_failure\nterminal_failure\nskipped\npossible_duplicate\n```\n\n`minimum_success_rank` is empty for non-success cases and otherwise one of:\n\n```text\naccepted\ndelivered\nacknowledged\n```\n\nProvider adapters preserve their actual status (`accepted`, `delivered` or\n`acknowledged`) and map it to the shared `success` class. This avoids forcing\nTeeBotus and the native worker to use the same internal success rank while still\ntesting monotonicity and minimum guarantees.",
        label="recipient expectation",
    )
    source = replace_once(
        source,
        "The safety object contains booleans:\n\n```text\nmust_not_auto_resend\nrequires_recipient_persistence_before_complete\nrequires_reconciliation_only_replay\n```",
        "The safety object contains exactly:\n\n```text\nmust_not_auto_resend\nrequires_recipient_persistence_before_complete\nrecovery_class\n```\n\nAllowed `recovery_class` values are:\n\n```text\nnone\nretryable\nterminal\nreconciliation_only\n```\n\n`reconciliation_only` means that a new transport send is forbidden. The native\nworker requires operator reconciliation; TeeBotus may replay only its already\ncreated encrypted callback through a reconciliation-only claim.",
        label="safety object",
    )
    source = replace_once(
        source,
        "python -m history_dispatcher.canary plan\npython -m history_dispatcher.canary run\npython -m history_dispatcher.canary verify\npython -m history_dispatcher.canary cleanup",
        "python -m history_dispatcher.canary plan\npython -m history_dispatcher.canary run\npython -m history_dispatcher.canary verify\npython -m history_dispatcher.canary compare\npython -m history_dispatcher.canary cleanup",
        label="command list",
    )
    source = replace_once(
        source,
        "`plan` is always write-free with respect to Telegram and production state. It:\n\n1. validates provider selection and `canary_` profiles;\n2. validates required executables and repository versions;\n3. creates no provider claim and performs no Secret-Service lookup;\n4. renders a canonical preview;\n5. produces a SHA-256 fingerprint and exact confirmation string.",
        "`plan` accepts exactly one provider-specific profile set:\n\n```text\nplan --provider history_dispatcher --credential-ref canary_<name> --recipient-ref canary_<name>\nplan --provider teebotus --instance-ref canary_<name> --recipient-ref canary_<name>\n```\n\nIt is always write-free with respect to Telegram and production state. It:\n\n1. validates provider selection and `canary_` profiles;\n2. resolves and records the current repository commits without modifying them;\n3. validates required executables and isolated-runtime prerequisites;\n4. creates no provider claim and performs no Secret-Service lookup;\n5. generates a new opaque run ID and ten-minute expiry;\n6. renders a canonical owner-only preview file;\n7. produces a SHA-256 fingerprint and exact confirmation string.",
        label="plan arguments",
    )
    source = replace_once(
        source,
        "--run-id <new opaque id>",
        "--run-id <opaque id copied from the plan file>",
        label="run id",
    )
    source = replace_once(
        source,
        "- different run IDs and canary nonce text;",
        "- different run IDs and different canary nonce hashes;",
        label="nonce comparison",
    )
    source = replace_once(
        source,
        "- wrong-provider preflight claims returned zero deliveries;",
        "- wrong-provider preflight claims returned zero claims;",
        label="wrong provider comparison",
    )
    SPEC.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
