import copy

from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.hitl.models import ReviewAction, ReviewItem, ReviewItemKind, ReviewResolution
from atlaz.hitl.resolution_application import apply_low_confidence_resolutions


def test_rejected_item_is_dropped():
    cluster = CapabilityCluster(capability_name="Misc", confidence=0.2)
    flagged = [
        ReviewItem(
            item_id="i1", kind=ReviewItemKind.LOW_CONFIDENCE_FINDING, source_domain="d", summary="",
            subject=cluster, natural_key="Misc",
        )
    ]
    resolutions = [ReviewResolution(item_id="i1", action=ReviewAction.REJECT)]

    result = apply_low_confidence_resolutions([cluster], flagged, resolutions)

    assert result == []


def test_accepted_item_is_replaced_by_resolved_value():
    cluster = CapabilityCluster(capability_name="Misc", confidence=0.2)
    edited = CapabilityCluster(capability_name="Reporting", confidence=0.2)
    flagged = [
        ReviewItem(
            item_id="i1", kind=ReviewItemKind.LOW_CONFIDENCE_FINDING, source_domain="d", summary="",
            subject=cluster, natural_key="Misc",
        )
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
        ReviewItem(
            item_id="i1", kind=ReviewItemKind.LOW_CONFIDENCE_FINDING, source_domain="d", summary="",
            subject=cluster, natural_key="Misc",
        )
    ]
    result = apply_low_confidence_resolutions([cluster], flagged, [])
    assert result == [cluster]


def test_matching_survives_a_checkpoint_style_round_trip():
    """Regression test: a LangGraph checkpoint round-trip (or, equivalently,
    an HTTP API handing resolutions back from a different process) does not
    preserve object identity -- `deepcopy` reproduces exactly that failure
    mode. Matching by `id()` alone would silently fail here and REJECT would
    do nothing; matching by natural_key must still work."""
    cluster = CapabilityCluster(capability_name="Misc", confidence=0.2)
    flagged = [
        ReviewItem(
            item_id="i1", kind=ReviewItemKind.LOW_CONFIDENCE_FINDING, source_domain="d", summary="",
            subject=copy.deepcopy(cluster), natural_key="Misc",
        )
    ]
    items_after_round_trip = [copy.deepcopy(cluster)]
    assert items_after_round_trip[0] is not cluster
    assert flagged[0].subject is not cluster

    resolutions = [ReviewResolution(item_id="i1", action=ReviewAction.REJECT)]
    result = apply_low_confidence_resolutions(items_after_round_trip, flagged, resolutions)

    assert result == []
