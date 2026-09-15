from atlaz.agents.domain_b.domain_glossary import DomainGlossaryExtractor
from atlaz.agents.domain_d.data_model_extractor import DataEntity
from atlaz.agents.domain_d.data_model_extractor import FieldInfo as DataFieldInfo
from atlaz.llm.client import MockLLMClient
from atlaz.parsing.models import ClassDef, CommentRecord, FunctionDef, ParseDepth, ParsedModule
from atlaz.shared.evidence import Evidence


def test_extracts_recurring_business_terms_and_filters_generic_vocabulary():
    module = ParsedModule(
        file_path="kyc/verify.py",
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        classes=[ClassDef(qualified_name="kyc.verify.KycVerifier", name="KycVerifier", line_start=1, line_end=10)],
        functions=[
            FunctionDef(qualified_name="kyc.verify.check_kyc", name="check_kyc", line_start=2, line_end=5),
            FunctionDef(qualified_name="kyc.verify.get_handler", name="get_handler", line_start=6, line_end=8),
        ],
        comments=[CommentRecord(text="kyc status must be verified before settlement", line=3)],
    )
    entity = DataEntity(
        entity_name="KycRecord",
        fields=[DataFieldInfo(name="kyc_status")],
        evidence=[Evidence(file="models.py", line=1)],
    )

    terms = DomainGlossaryExtractor(MockLLMClient()).run([module], data_entities=[entity])

    term_names = {t.term for t in terms}
    assert "kyc" in term_names
    assert "settlement" not in term_names  # appears once, single source -- below the signal bar
    assert "handler" not in term_names  # stoplisted generic term

    kyc_term = next(t for t in terms if t.term == "kyc")
    assert kyc_term.occurrence_count >= 3
    assert set(kyc_term.source_kinds) >= {"class_name", "comment", "db_column"}
    assert kyc_term.tier.value == "inferable"
    assert kyc_term.definition
