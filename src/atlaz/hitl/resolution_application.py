"""Folds `hitl_resolutions` back into a domain list before it reaches the
graph writer (LLD Section 10.2's reviewer actions: accept / edit / reject).

Matching a resolution back to the object it resolves is done by identity
(`id(obj)`), not by re-deriving a key: `ReviewItem.subject` in
`flagged_for_review` is the *same object* as the one sitting in the
domain-B/C/D list (they were flagged from, and still live in, that list),
so this never needs its own notion of "what identifies a BusinessRule."
"""

from __future__ import annotations

from atlaz.hitl.models import ReviewAction, ReviewItem, ReviewItemKind, ReviewResolution


def apply_low_confidence_resolutions(items: list, flagged: list[ReviewItem], resolutions: list[ReviewResolution]) -> list:
    """Returns a new list: REJECTed items dropped, ACCEPTed/EDITed items
    replaced by `resolution.resolved_value`, untouched items unchanged. A
    flagged item with no matching resolution is kept as-is rather than
    dropped -- losing data to a wiring gap is worse than leaving a finding
    at its original (still-visible, still low-confidence) state."""
    resolution_by_id = {r.item_id: r for r in resolutions}
    flagged_by_object_id = {
        id(item.subject): item for item in flagged if item.kind == ReviewItemKind.LOW_CONFIDENCE_FINDING
    }

    result = []
    for obj in items:
        flagged_item = flagged_by_object_id.get(id(obj))
        if flagged_item is None:
            result.append(obj)
            continue
        resolution = resolution_by_id.get(flagged_item.item_id)
        if resolution is None:
            result.append(obj)
        elif resolution.action == ReviewAction.REJECT:
            continue
        else:
            result.append(resolution.resolved_value)
    return result


def find_gap_resolution(flagged: list[ReviewItem], resolutions: list[ReviewResolution]) -> ReviewResolution | None:
    gap_item = next((i for i in flagged if i.kind == ReviewItemKind.GAP_CONFIRMATION), None)
    if gap_item is None:
        return None
    return next((r for r in resolutions if r.item_id == gap_item.item_id), None)


def conflict_resolutions(resolutions: list[ReviewResolution]) -> list[ReviewResolution]:
    return [r for r in resolutions if r.action == ReviewAction.RESOLVE_CONFLICT]
