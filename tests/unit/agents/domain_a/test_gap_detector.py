import dataclasses

import pytest

from atlaz.agents.domain_a.gap_detector import BusinessCaseGapDetector
from atlaz.agents.domain_a.readme_commit_signal_miner import CandidateSignal
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier


def test_tier_and_status_are_always_external_only_and_cannot_be_reassigned():
    finding = BusinessCaseGapDetector().run(signals=[])

    assert finding.tier == Tier.EXTERNAL_ONLY
    assert finding.status == "external_only"
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.tier = Tier.INFERABLE  # type: ignore[misc]


def test_no_signal_still_produces_gap_evidence():
    finding = BusinessCaseGapDetector().run(signals=[])

    assert finding.signal_found is False
    assert finding.evidence == [Evidence.gap()]
    assert finding.routed_to == "hitl_gate"


def test_signals_are_carried_through_unmodified():
    signal = CandidateSignal(source_kind="readme", text="this exists because manual audits were slow", evidence=Evidence(file="README.md", line=1))

    finding = BusinessCaseGapDetector().run(signals=[signal])

    assert finding.signal_found is True
    assert finding.candidate_signals == [signal]
    assert finding.evidence == [signal.evidence]
    assert finding.tier == Tier.EXTERNAL_ONLY
