from atlaz.agents.domain_d.data_model_extractor import DataEntity
from atlaz.agents.domain_d.data_model_extractor import FieldInfo as DataFieldInfo
from atlaz.agents.domain_d.security_control_scanner import SecurityControlScanner
from atlaz.llm.client import MockLLMClient
from atlaz.parsing.models import CallEdge, ImportEdge, ParseDepth, ParsedModule


def test_detects_auth_and_encryption_imports():
    module = ParsedModule(
        file_path="auth/login.py",
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        imports=[
            ImportEdge(source_module="auth.login", imported="flask_jwt_extended", line=1),
            ImportEdge(source_module="auth.login", imported="bcrypt", line=2),
        ],
    )

    controls = SecurityControlScanner(MockLLMClient()).run([module])

    types = {c.control_type for c in controls}
    assert "auth" in types
    assert "encryption" in types
    for c in controls:
        assert c.tier.value == "extractable"
        assert c.regulation_hypothesis is None  # only pii_handling gets a regulation hypothesis


def test_detects_audit_log_calls():
    module = ParsedModule(
        file_path="orders/service.py",
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        calls=[CallEdge(caller="orders.service.place_order", callee="audit_log", line=42)],
    )

    controls = SecurityControlScanner(MockLLMClient()).run([module])

    assert any(c.control_type == "audit_log" for c in controls)


def test_detects_pii_fields_and_hypothesizes_regulation_separately_tiered():
    entity = DataEntity(entity_name="Customer", fields=[DataFieldInfo(name="email"), DataFieldInfo(name="name")])

    controls = SecurityControlScanner(MockLLMClient()).run([], data_entities=[entity])

    pii_controls = [c for c in controls if c.control_type == "pii_handling"]
    assert len(pii_controls) == 1
    assert "email" in pii_controls[0].detail
    assert pii_controls[0].tier.value == "extractable"
    assert pii_controls[0].regulation_hypothesis is not None
    assert pii_controls[0].regulation_confidence is not None
