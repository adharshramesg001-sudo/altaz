from atlaz.agents.domain_a.gap_detector import GapFinding
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.api.resolution_builder import build_resolutions
from atlaz.api.schemas import ResolutionRequest
from atlaz.hitl.models import ReviewAction, ReviewItem, ReviewItemKind


def _gap_item() -> ReviewItem:
    return ReviewItem(
        item_id="domain_a::business_case_vision", kind=ReviewItemKind.GAP_CONFIRMATION,
        source_domain="domain_a", summary="", subject=GapFinding(),
    )


def _low_confidence_item() -> ReviewItem:
    cluster = CapabilityCluster(capability_name="Misc", confidence=0.3)
    return ReviewItem(
        item_id="low_confidence::domain_b::Misc", kind=ReviewItemKind.LOW_CONFIDENCE_FINDING,
        source_domain="domain_b", summary="", subject=cluster, natural_key="Misc",
    )


def test_gap_accept_with_answer_produces_accept_resolution():
    item = _gap_item()
    reqs = [ResolutionRequest(item_id=item.item_id, action="accept", answer="This tool exists for compliance audits.")]

    resolutions = build_resolutions([item], reqs)

    assert len(resolutions) == 1
    assert resolutions[0].action == ReviewAction.ACCEPT
    assert resolutions[0].resolved_value == "This tool exists for compliance audits."


def test_gap_accept_without_answer_falls_back_to_reject():
    item = _gap_item()
    reqs = [ResolutionRequest(item_id=item.item_id, action="accept", answer="")]

    resolutions = build_resolutions([item], reqs)

    assert resolutions[0].action == ReviewAction.REJECT


def test_low_confidence_reject_excludes_it():
    item = _low_confidence_item()
    reqs = [ResolutionRequest(item_id=item.item_id, action="reject")]

    resolutions = build_resolutions([item], reqs)

    assert resolutions[0].action == ReviewAction.REJECT


def test_low_confidence_accept_uses_original_subject():
    item = _low_confidence_item()
    reqs = [ResolutionRequest(item_id=item.item_id, action="accept")]

    resolutions = build_resolutions([item], reqs)

    assert resolutions[0].action == ReviewAction.ACCEPT
    assert resolutions[0].resolved_value is item.subject


def test_uncovered_items_are_auto_resolved():
    gap = _gap_item()
    low_conf = _low_confidence_item()

    resolutions = build_resolutions([gap, low_conf], [])

    assert len(resolutions) == 2
    assert {r.reviewer for r in resolutions} == {"auto-resolve-policy"}


def test_unknown_item_id_in_request_is_ignored_not_erroring():
    gap = _gap_item()
    reqs = [ResolutionRequest(item_id="does-not-exist", action="accept", answer="x")]

    resolutions = build_resolutions([gap], reqs)

    # the unknown request is dropped; the real gap item still gets auto-resolved
    assert len(resolutions) == 1
    assert resolutions[0].item_id == gap.item_id
    assert resolutions[0].reviewer == "auto-resolve-policy"
