from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Evidence, Finding, RequestType, Severity


class PolicyEngine:
    """Config-driven business and safety rules."""

    def __init__(self, policy_path: Path):
        self.policy_path = policy_path
        self.config = json.loads(policy_path.read_text(encoding="utf-8"))

    @property
    def supported_request_types(self) -> set[str]:
        return set(self.config["request_types"])

    def required_fields(self, request_type: RequestType) -> list[str]:
        return list(self.config["required_fields"][request_type.value])

    def validate_request(
        self,
        request_type: RequestType,
        partner: Any | None,
        contract: Any | None,
        fields: dict[str, Any],
        duplicate_count: int = 0,
    ) -> list[Finding]:
        findings: list[Finding] = []
        missing = [f for f in self.required_fields(request_type) if not fields.get(f)]
        if missing:
            findings.append(
                Finding(
                    "MISSING_REQUIRED_FIELDS",
                    Severity.CRITICAL,
                    f"Required information is missing: {', '.join(missing)}",
                    tuple(
                        Evidence("Request", "Field", f, f, fields.get(f), "Required by policy")
                        for f in missing
                    ),
                )
            )

        if request_type in {RequestType.CONTRACT_CREATION, RequestType.CONTRACT_AMENDMENT, RequestType.CONTRACT_TERMINATION} and not contract and request_type != RequestType.CONTRACT_CREATION:
            # Amendment/termination must identify a real existing contract.
            pass

        amount = fields.get("annual_value")
        if amount is not None:
            try:
                if float(amount) <= 0:
                    findings.append(Finding("INVALID_ANNUAL_VALUE", Severity.CRITICAL, "Annual contract value must be greater than zero."))
            except (TypeError, ValueError):
                findings.append(Finding("INVALID_ANNUAL_VALUE", Severity.CRITICAL, "Annual contract value must be numeric."))

        currency = fields.get("currency") or getattr(partner, "currency", None) or getattr(contract, "currency", None)
        if currency and currency not in self.config["supported_currencies"]:
            findings.append(
                Finding(
                    "UNSUPPORTED_CURRENCY",
                    Severity.CRITICAL,
                    f"Currency {currency!r} is not allowed by the configured policy.",
                )
            )

        if duplicate_count:
            severity = Severity.CRITICAL if duplicate_count > self.config["duplicate_candidate_critical_threshold"] else Severity.HIGH
            findings.append(
                Finding(
                    "POSSIBLE_DUPLICATE_PARTNER",
                    severity,
                    f"Found {duplicate_count} possible duplicate partner record(s).",
                )
            )

        if request_type == RequestType.CONTRACT_TERMINATION and contract:
            if getattr(contract, "status", "") != "ACTIVE":
                findings.append(
                    Finding(
                        "CONTRACT_NOT_ACTIVE",
                        Severity.WARNING,
                        "The selected contract is not currently ACTIVE.",
                        (Evidence("ContractSystem", "Contract", contract.contract_id, "status", contract.status, "Current contract state"),),
                    )
                )
            if getattr(contract, "open_obligations", 0) > 0:
                findings.append(
                    Finding(
                        "OPEN_OBLIGATIONS",
                        Severity.CRITICAL,
                        f"Contract has {contract.open_obligations} open obligation(s); termination is blocked until they are resolved.",
                        (Evidence("ContractSystem", "Contract", contract.contract_id, "open_obligations", contract.open_obligations, "Termination safety check"),),
                    )
                )

        if request_type == RequestType.CONTRACT_AMENDMENT and contract:
            proposed = fields.get("proposed_annual_value")
            if proposed is not None:
                old = float(contract.annual_value)
                new = float(proposed)
                base = abs(old) or 1.0
                delta = abs(new - old) / base
                if delta >= self.config["high_value_change_ratio"]:
                    findings.append(
                        Finding(
                            "HIGH_VALUE_CHANGE",
                            Severity.HIGH,
                            f"Annual contract value changes by {delta:.1%}; enhanced review is required.",
                            (Evidence("ContractSystem", "Contract", contract.contract_id, "annual_value", old, "Existing value"),
                             Evidence("Request", "Field", "proposed_annual_value", "proposed_annual_value", new, "Requested value")),
                        )
                    )
                elif delta >= self.config["review_value_change_ratio"]:
                    findings.append(
                        Finding(
                            "MATERIAL_VALUE_CHANGE",
                            Severity.WARNING,
                            f"Annual contract value changes by {delta:.1%}; reviewer should confirm the change.",
                            (Evidence("ContractSystem", "Contract", contract.contract_id, "annual_value", old, "Existing value"),
                             Evidence("Request", "Field", "proposed_annual_value", "proposed_annual_value", new, "Requested value")),
                        )
                    )

        return findings

    def blocks(self, findings: list[Finding]) -> bool:
        return any(f.severity in {Severity.CRITICAL} for f in findings)

    def needs_enhanced_review(self, findings: list[Finding]) -> bool:
        return any(f.severity == Severity.HIGH for f in findings)
