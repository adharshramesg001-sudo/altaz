"""Translates HTTP `ResolutionRequest` bodies into real `ReviewResolution`
objects, looking up each item's actual `subject` from the freshly-read
flagged queue rather than trusting the client to supply one.

Any flagged item the client's request doesn't mention is auto-resolved
(LLD Section 10.3's fixed policy) rather than left dangling -- a partial
HTTP resolution list must not leave the run stuck.
"""

from __future__ import annotations

from atlaz.api.schemas import ResolutionRequest
from atlaz.hitl.auto_resolve import auto_resolve
from atlaz.hitl.models import ReviewAction, ReviewItem, ReviewItemKind, ReviewResolution


def build_resolutions(flagged: list[ReviewItem], requests: list[ResolutionRequest]) -> list[ReviewResolution]:
    flagged_by_id = {item.item_id: item for item in flagged}
    resolutions: list[ReviewResolution] = []
    covered_ids: set[str] = set()

    for req in requests:
        item = flagged_by_id.get(req.item_id)
        if item is None:
            continue  # unknown item_id in the request; silently ignored rather than erroring the whole batch
        covered_ids.add(req.item_id)
        resolutions.append(_build_one(item, req))

    remaining = [item for item in flagged if item.item_id not in covered_ids]
    resolutions.extend(auto_resolve(remaining))
    return resolutions


def _build_one(item: ReviewItem, req: ResolutionRequest) -> ReviewResolution:
    if item.kind == ReviewItemKind.GAP_CONFIRMATION:
        if req.action == "accept" and req.answer and req.answer.strip():
            return ReviewResolution(
                item_id=item.item_id, action=ReviewAction.ACCEPT, resolved_value=req.answer.strip(),
                reviewer=req.reviewer, resolution_note=req.note,
            )
        return ReviewResolution(
            item_id=item.item_id, action=ReviewAction.REJECT, resolved_value=None,
            reviewer=req.reviewer, resolution_note=req.note or "no info available",
        )

    # LOW_CONFIDENCE_FINDING
    if req.action == "reject":
        return ReviewResolution(item_id=item.item_id, action=ReviewAction.REJECT, reviewer=req.reviewer, resolution_note=req.note)
    return ReviewResolution(
        item_id=item.item_id, action=ReviewAction.ACCEPT, resolved_value=item.subject,
        reviewer=req.reviewer, resolution_note=req.note,
    )
