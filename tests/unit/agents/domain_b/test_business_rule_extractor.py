from pathlib import Path

from atlaz.agents.domain_b.business_rule_extractor import BusinessRuleExtractor
from atlaz.ingestion.repo_ingestor import RepoIngestor
from atlaz.llm.client import MockLLMClient

SOURCE = '''
LATE_FEE_RATE = 0.045
MAX_RETRY_COUNT = 3
greeting = "hello"


def compute():
    discount_threshold = 100
    return discount_threshold
'''


def test_extracts_business_suggestive_literals_from_code(tmp_path: Path):
    (tmp_path / "billing.py").write_text(SOURCE)
    inventory = RepoIngestor().ingest(str(tmp_path))

    rules = BusinessRuleExtractor(MockLLMClient()).run(inventory)

    identifiers = {r.rule_id.split("::")[-1] for r in rules if r.source_kind == "code_literal"}
    assert "LATE_FEE_RATE" in identifiers
    assert "discount_threshold" in identifiers
    assert "greeting" not in identifiers  # no business-suggestive keyword

    late_fee = next(r for r in rules if r.rule_id.endswith("LATE_FEE_RATE"))
    assert late_fee.literal_value == "0.045"
    assert late_fee.tier.value == "extractable"
    assert late_fee.confidence >= 0.9
    assert late_fee.description  # LLM-generated, non-empty


def test_extracts_business_suggestive_values_from_config(tmp_path: Path):
    (tmp_path / "settings.yaml").write_text("payments:\n  late_fee_rate: 0.05\n  currency: USD\n")
    inventory = RepoIngestor().ingest(str(tmp_path))

    rules = BusinessRuleExtractor(MockLLMClient()).run(inventory)

    config_rules = {r.rule_id: r.literal_value for r in rules if r.source_kind == "config_value"}
    assert "settings.yaml::payments.late_fee_rate" in config_rules
    assert config_rules["settings.yaml::payments.late_fee_rate"] == "0.05"
    assert not any("currency" in k for k in config_rules)
