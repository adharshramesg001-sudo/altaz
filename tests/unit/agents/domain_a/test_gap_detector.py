import dataclasses

import pytest

from atlaz.agents.domain_a.gap_detector import BusinessCaseGapDetector
from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.ingestion.repo_ingestor import RepoIngestor
from atlaz.parsing.models import ClassDef, FieldSpec, ParseDepth, ParsedModule
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier


def test_tier_is_always_external_only_and_cannot_be_reassigned(tmp_path):
    inventory = RepoIngestor().ingest(str(tmp_path))
    finding = BusinessCaseGapDetector().run(inventory, parsed=[])

    assert finding.tier == Tier.EXTERNAL_ONLY
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.tier = Tier.INFERABLE  # type: ignore[misc]


def test_no_signal_still_produces_gap_evidence(tmp_path):
    inventory = RepoIngestor().ingest(str(tmp_path))
    finding = BusinessCaseGapDetector().run(inventory, parsed=[])

    assert finding.signal_found is False
    assert finding.evidence == [Evidence.gap()]
    assert finding.routed_to == "hitl_gate"


def test_readme_rationale_language_becomes_a_candidate_signal(tmp_path):
    (tmp_path / "README.md").write_text("This tool exists to help teams because manual audits were too slow.")
    inventory = RepoIngestor().ingest(str(tmp_path))

    finding = BusinessCaseGapDetector().run(inventory, parsed=[])

    assert finding.signal_found
    readme_signals = [s for s in finding.candidate_signals if s.source_kind == "readme"]
    assert readme_signals
    assert "because" in readme_signals[0].text.lower()


def test_billing_structure_is_surfaced_as_raw_signal_not_a_conclusion(tmp_path):
    module = ParsedModule(
        file_path="billing/plans.py",
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        classes=[
            ClassDef(
                qualified_name="billing.plans.PlanTier",
                name="PlanTier",
                line_start=1,
                line_end=5,
                fields=[FieldSpec(name="pricing_tier", value_expr="'gold'", line=2)],
            )
        ],
    )
    inventory = RepoIngestor().ingest(str(tmp_path))

    finding = BusinessCaseGapDetector().run(inventory, parsed=[module])

    billing_signals = [s for s in finding.candidate_signals if s.source_kind == "billing_structure"]
    assert billing_signals
    # raw evidence only -- never phrased as a strategy conclusion
    assert "pricing strategy" not in billing_signals[0].text.lower()
    assert finding.tier == Tier.EXTERNAL_ONLY


def test_glossary_terms_feed_naming_pattern_signals(tmp_path):
    glossary = [
        GlossaryTerm(term="settlement", occurrence_count=5, source_kinds=["class_name"], evidence=[Evidence(file="a.py", line=1)])
    ]
    inventory = RepoIngestor().ingest(str(tmp_path))

    finding = BusinessCaseGapDetector().run(inventory, parsed=[], glossary=glossary)

    naming_signals = [s for s in finding.candidate_signals if s.source_kind == "naming_pattern"]
    assert any(s.text == "settlement" for s in naming_signals)
