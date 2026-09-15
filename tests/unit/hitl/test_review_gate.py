import pytest

from atlaz.agents.domain_a.gap_detector import GapFinding
from atlaz.hitl.models import ReviewItem, ReviewItemKind
from atlaz.hitl.review_gate import ReviewGate
from atlaz.shared.config import PipelineConfig


def _gap_item() -> ReviewItem:
    return ReviewItem(
        item_id="domain_a::business_case_vision",
        kind=ReviewItemKind.GAP_CONFIRMATION,
        source_domain="domain_a",
        summary="gap",
        subject=GapFinding(),
    )


def test_hitl_disabled_uses_auto_resolve_and_never_picks_a_conflict_side():
    config = PipelineConfig(hitl_enabled=False)
    resolutions = ReviewGate().route([_gap_item()], config)
    assert len(resolutions) == 1
    assert resolutions[0].reviewer == "auto-resolve-policy"


def test_hitl_enabled_without_interrupt_fn_raises():
    config = PipelineConfig(hitl_enabled=True)
    with pytest.raises(RuntimeError):
        ReviewGate().route([_gap_item()], config)


def test_hitl_enabled_delegates_to_interrupt_fn():
    config = PipelineConfig(hitl_enabled=True)
    seen = {}

    def fake_interrupt(flagged):
        seen["flagged"] = flagged
        return []

    ReviewGate().route([_gap_item()], config, interrupt_fn=fake_interrupt)
    assert "flagged" in seen


def test_empty_queue_short_circuits_without_calling_interrupt():
    config = PipelineConfig(hitl_enabled=True)

    def should_not_be_called(flagged):
        raise AssertionError("interrupt_fn must not be called for an empty queue")

    assert ReviewGate().route([], config, interrupt_fn=should_not_be_called) == []
