from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.hitl.models import ReviewAction, ReviewItem, ReviewItemKind, ReviewResolution
from atlaz.hitl.resolution_application import apply_low_confidence_resolutions


def test_rejected_item_is_dropped():
    cluster = CapabilityCluster(capability_name="Misc", confidence=0.2)
    flagged = [
        ReviewItem(item_id="i1", kind=ReviewItemKind.LOW_CONFIDENCE_FINDING, source_domain="d", summary="", subject=cluster)
    ]
    resolutions = [ReviewResolution(item_id="i1", action=ReviewAction.REJECT)]

    result = apply_low_confidence_resolutions([cluster], flagged, resolutions)

    assert result == []


def test_accepted_item_is_replaced_by_resolved_value():
    cluster = CapabilityCluster(capability_name="Misc", confidence=0.2)
    edited = CapabilityCluster(capability_name="Reporting", confidence=0.2)
    flagged = [
        ReviewItem(item_id="i1", kind=ReviewItemKind.LOW_CONFIDENCE_FINDING, source_domain="d", summary="", subject=cluster)
    ]
    resolutions = [ReviewResolution(item_id="i1", action=ReviewAction.EDIT, resolved_value=edited)]

    result = apply_low_confidence_resolutions([cluster], flagged, resolutions)

    assert result == [edited]


def test_unflagged_item_passes_through_unchanged():
    cluster = CapabilityCluster(capability_name="Orders", confidence=0.95)
    result = apply_low_confidence_resolutions([cluster], [], [])
    assert result == [cluster]


def test_flagged_item_with_missing_resolution_is_kept():
    cluster = CapabilityCluster(capability_name="Misc", confidence=0.2)
    flagged = [
        ReviewItem(item_id="i1", kind=ReviewItemKind.LOW_CONFIDENCE_FINDING, source_domain="d", summary="", subject=cluster)
    ]
    result = apply_low_confidence_resolutions([cluster], flagged, [])
    assert result == [cluster]
