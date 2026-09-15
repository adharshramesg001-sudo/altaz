"""Security Control Scanner Agent (LLD Section 8.5, Corner #17).

Adds no new parsing: it re-reads `ParsedModule`/`DataEntity` output already
produced by Sections 4 and 8.3 through a security-pattern lens. Per the
HLD's explicit instruction to "cite the control, don't name the law unless
documented," `regulation_hypothesis` is generated separately and tiered
INFERABLE with its own (typically lower) confidence -- the
control_type/location/detail facts never inherit that hypothesis's lower
confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlaz.agents.domain_d.data_model_extractor import DataEntity
from atlaz.llm.client import BaseLLMClient
from atlaz.parsing.models import ParsedModule
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier

AUTH_IMPORT_PATTERNS = (
    "flask_login",
    "flask_jwt",
    "django.contrib.auth",
    "passport",
    "jsonwebtoken",
    "jwt",
    "oauthlib",
    "authlib",
    "spring.security",
    "devise",
    "keycloak",
)
ENCRYPTION_IMPORT_PATTERNS = (
    "cryptography",
    "hashlib",
    "bcrypt",
    "pyca",
    "crypto",
    "openssl",
    "javax.crypto",
    "libsodium",
)
AUDIT_LOG_CALL_PATTERNS = ("audit_log", "audit", "log_action", "record_event")
PII_FIELD_NAMES = frozenset(
    {
        "email",
        "ssn",
        "social_security_number",
        "dob",
        "date_of_birth",
        "phone",
        "phone_number",
        "address",
        "credit_card",
        "card_number",
        "passport_number",
        "national_id",
    }
)

_REGULATION_SCHEMA = {
    "type": "object",
    "properties": {
        "regulation_hypothesis": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["regulation_hypothesis", "confidence"],
}


@dataclass(slots=True)
class SecurityControl:
    control_type: str  # "auth" | "encryption" | "pii_handling" | "audit_log"
    location: str
    detail: str
    regulation_hypothesis: str | None = None
    regulation_confidence: float | None = None
    tier: Tier = Tier.EXTRACTABLE  # governs control_type/location/detail; hypothesis is separately tiered
    confidence: float = 0.9
    evidence: list[Evidence] = field(default_factory=list)


class SecurityControlScanner:
    def __init__(self, llm_client: BaseLLMClient) -> None:
        self.llm_client = llm_client

    def run(self, parsed: list[ParsedModule], data_entities: list[DataEntity] | None = None) -> list[SecurityControl]:
        controls: list[SecurityControl] = []
        controls.extend(self._scan_auth_and_encryption_imports(parsed))
        controls.extend(self._scan_audit_log_calls(parsed))
        controls.extend(self._scan_pii_fields(data_entities or []))

        for control in controls:
            control.regulation_hypothesis, control.regulation_confidence = self._hypothesize_regulation(control)
        return controls

    def _scan_auth_and_encryption_imports(self, parsed: list[ParsedModule]) -> list[SecurityControl]:
        controls: list[SecurityControl] = []
        for module in parsed:
            for imp in module.imports:
                lowered = imp.imported.lower()
                if any(pattern in lowered for pattern in AUTH_IMPORT_PATTERNS):
                    controls.append(
                        SecurityControl(
                            control_type="auth",
                            location=module.file_path,
                            detail=f"imports {imp.imported}",
                            evidence=[Evidence(file=module.file_path, line=imp.line)],
                        )
                    )
                elif any(pattern in lowered for pattern in ENCRYPTION_IMPORT_PATTERNS):
                    controls.append(
                        SecurityControl(
                            control_type="encryption",
                            location=module.file_path,
                            detail=f"imports {imp.imported}",
                            evidence=[Evidence(file=module.file_path, line=imp.line)],
                        )
                    )
        return controls

    def _scan_audit_log_calls(self, parsed: list[ParsedModule]) -> list[SecurityControl]:
        controls: list[SecurityControl] = []
        for module in parsed:
            for call in module.calls:
                if any(pattern in call.callee.lower() for pattern in AUDIT_LOG_CALL_PATTERNS):
                    controls.append(
                        SecurityControl(
                            control_type="audit_log",
                            location=module.file_path,
                            detail=f"calls {call.callee}() from {call.caller}",
                            evidence=[Evidence(file=module.file_path, line=call.line)],
                        )
                    )
        return controls

    def _scan_pii_fields(self, data_entities: list[DataEntity]) -> list[SecurityControl]:
        controls: list[SecurityControl] = []
        for entity in data_entities:
            for field_info in entity.fields:
                if field_info.name.lower() in PII_FIELD_NAMES:
                    evidence = entity.evidence[0] if entity.evidence else Evidence.gap()
                    controls.append(
                        SecurityControl(
                            control_type="pii_handling",
                            location=entity.entity_name,
                            detail=f"field '{field_info.name}' on entity '{entity.entity_name}'",
                            evidence=[evidence],
                        )
                    )
        return controls

    def _hypothesize_regulation(self, control: SecurityControl) -> tuple[str | None, float | None]:
        if control.control_type != "pii_handling":
            return None, None
        prompt = (
            "A codebase handles a personal-data field described as: "
            f"{control.detail}. Name the single most likely data-protection regulation this control "
            "might relate to (e.g. GDPR, CCPA, HIPAA), or 'unknown' if there is no strong signal. "
            "This is a hypothesis, not a documented fact."
        )
        result = self.llm_client.complete_json(prompt, schema=_REGULATION_SCHEMA)
        hypothesis = result.get("regulation_hypothesis") or "unknown"
        try:
            confidence = float(result.get("confidence", 0.3))
        except (TypeError, ValueError):
            confidence = 0.3
        return hypothesis, max(0.0, min(1.0, confidence))
